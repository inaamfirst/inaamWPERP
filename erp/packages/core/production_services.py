from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
import uuid
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import inspect, text
from sqlalchemy.exc import SQLAlchemyError

from erp.packages.core.config import Settings, get_settings
from erp.packages.core.db.session import create_database_engine
from erp.packages.core.diagnostics_services import (
    expected_migration_revision,
    missing_required_runtime_tables,
)


@dataclass(frozen=True)
class ProductionPreflightCheck:
    name: str
    ok: bool
    detail: str
    required: bool = True


@dataclass(frozen=True)
class ProductionPreflight:
    environment: str
    checked_at: datetime
    checks: tuple[ProductionPreflightCheck, ...]

    @property
    def ok(self) -> bool:
        return all(check.ok or not check.required for check in self.checks)

    def as_dict(self) -> dict[str, object]:
        return {
            "environment": self.environment,
            "checked_at": self.checked_at.isoformat(),
            "ok": self.ok,
            "checks": [asdict(check) for check in self.checks],
        }


def _now() -> datetime:
    return datetime.now(UTC)


def _safe_exception_detail(exc: Exception) -> str:
    """Return diagnostics without database credentials or other secrets."""

    message = str(exc).replace("\n", " ").strip()
    if not message:
        return type(exc).__name__
    # SQLAlchemy can include a complete connection URL in some error messages.
    if "://" in message and "@" in message:
        prefix, _separator, suffix = message.partition("://")
        message = f"{prefix}://***@{suffix.rsplit('@', 1)[-1]}"
    return message[:300]


def _path_writable_check(name: str, value: str) -> ProductionPreflightCheck:
    path = Path(value).expanduser()
    probe = path / f".erp-preflight-{uuid.uuid4().hex}.tmp"
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
    except OSError as exc:
        try:
            probe.unlink(missing_ok=True)
        except OSError:
            pass
        return ProductionPreflightCheck(
            name,
            False,
            f"{path}: not writable ({_safe_exception_detail(exc)})",
        )
    return ProductionPreflightCheck(name, True, f"{path}: writable")


def worker_heartbeat_path(settings: Settings | None = None) -> Path:
    active_settings = settings or get_settings()
    return Path(active_settings.worker_heartbeat_file).expanduser()


def write_worker_heartbeat(
    *,
    worker_id: str,
    status: str,
    run_id: str | None = None,
    settings: Settings | None = None,
) -> bool:
    """Atomically publish the worker's last known state for operators/preflight."""

    target = worker_heartbeat_path(settings)
    payload = {
        "worker_id": worker_id,
        "status": status,
        "run_id": run_id,
        "updated_at": _now().isoformat(),
    }
    temporary = target.with_name(f".{target.name}.{uuid.uuid4().hex}.tmp")
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
        os.replace(temporary, target)
        return True
    except OSError:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
        return False


def read_worker_heartbeat(settings: Settings | None = None) -> dict[str, object] | None:
    target = worker_heartbeat_path(settings)
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return None
    return payload if isinstance(payload, dict) else None


def _worker_heartbeat_check(settings: Settings) -> ProductionPreflightCheck:
    heartbeat = read_worker_heartbeat(settings)
    if heartbeat is None:
        return ProductionPreflightCheck(
            "worker_heartbeat",
            False,
            "Worker heartbeat is missing. Start the managed ERP worker and retry preflight.",
        )
    raw_updated_at = heartbeat.get("updated_at")
    try:
        updated_at = datetime.fromisoformat(str(raw_updated_at).replace("Z", "+00:00"))
        if updated_at.tzinfo is None:
            updated_at = updated_at.replace(tzinfo=UTC)
    except ValueError:
        return ProductionPreflightCheck(
            "worker_heartbeat",
            False,
            "Worker heartbeat has an invalid timestamp.",
        )
    freshness_limit = max(120, settings.worker_poll_seconds * 3 + 30)
    if _now() - updated_at.astimezone(UTC) > timedelta(seconds=freshness_limit):
        return ProductionPreflightCheck(
            "worker_heartbeat",
            False,
            f"Worker heartbeat is older than {freshness_limit} seconds.",
        )
    return ProductionPreflightCheck(
        "worker_heartbeat",
        True,
        (
            f"Worker {heartbeat.get('worker_id') or 'unknown'} is "
            f"{heartbeat.get('status') or 'unknown'}."
        ),
    )


def _database_checks(settings: Settings) -> list[ProductionPreflightCheck]:
    expected_revision = expected_migration_revision()
    engine = create_database_engine(settings)
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
            inspector = inspect(connection)
            if "alembic_version" not in inspector.get_table_names():
                current_revision = None
            else:
                current_revision = connection.execute(
                    text("SELECT version_num FROM alembic_version")
                ).scalar_one_or_none()
            missing_tables = missing_required_runtime_tables(connection)
    except SQLAlchemyError as exc:
        detail = _safe_exception_detail(exc)
        return [
            ProductionPreflightCheck("postgresql_connection", False, detail),
            ProductionPreflightCheck("database_migrations", False, "Database is unavailable."),
        ]
    finally:
        engine.dispose()

    migration_ok = bool(
        expected_revision
        and current_revision == expected_revision
        and not missing_tables
    )
    if missing_tables:
        migration_detail = (
            "Database is missing required runtime tables: "
            + ", ".join(missing_tables)
            + "."
        )
    elif migration_ok:
        migration_detail = (
            f"Migration revision {current_revision} matches head {expected_revision}."
        )
    else:
        migration_detail = (
            f"Migration revision {current_revision or 'none'} does not match head "
            f"{expected_revision or 'unknown'}."
        )
    return [
        ProductionPreflightCheck("postgresql_connection", True, "PostgreSQL connection succeeded."),
        ProductionPreflightCheck(
            "database_migrations",
            migration_ok,
            migration_detail,
        ),
    ]


def _backup_tool_check() -> ProductionPreflightCheck:
    executable = shutil.which("pg_dump")
    if executable is None:
        return ProductionPreflightCheck(
            "postgres_backup_tool",
            False,
            (
                "pg_dump was not found on PATH. Install PostgreSQL client tools "
                "for the service account."
            ),
        )
    return ProductionPreflightCheck(
        "postgres_backup_tool", True, f"pg_dump available at {executable}."
    )


def _env_file_check() -> ProductionPreflightCheck:
    configured_path = os.environ.get("ERP_CONFIG_FILE", ".env")
    path = Path(configured_path).expanduser()
    if not path.exists():
        return ProductionPreflightCheck(
            "environment_file_permissions",
            True,
            "No .env file was found; configuration is supplied by the managed environment.",
            required=False,
        )
    if os.name != "nt":
        try:
            mode = stat.S_IMODE(path.stat().st_mode)
        except OSError as exc:
            return ProductionPreflightCheck(
                "environment_file_permissions",
                False,
                f"Cannot read permissions for {path}: {_safe_exception_detail(exc)}",
            )
        if mode & (stat.S_IRWXG | stat.S_IRWXO):
            return ProductionPreflightCheck(
                "environment_file_permissions",
                False,
                f"{path} grants group or other access; restrict it to the service account.",
            )
        return ProductionPreflightCheck(
            "environment_file_permissions",
            True,
            f"{path} is restricted to its owner.",
        )
    try:
        acl = subprocess.run(
            ["icacls", str(path)],
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return ProductionPreflightCheck(
            "environment_file_permissions",
            True,
            f"Could not inspect ACLs for {path}; verify it is restricted to the service account.",
            required=False,
        )
    if acl.returncode != 0:
        return ProductionPreflightCheck(
            "environment_file_permissions",
            False,
            f"Could not inspect ACLs for {path} (icacls exited {acl.returncode}).",
        )
    acl_text = acl.stdout.lower()
    broad_principals = ("everyone:", "builtin\\users:", "authenticated users:")
    if any(principal in acl_text for principal in broad_principals):
        return ProductionPreflightCheck(
            "environment_file_permissions",
            False,
            f"{path} grants a broad Windows principal access; restrict the .env file.",
        )
    return ProductionPreflightCheck(
        "environment_file_permissions",
        True,
        f"{path} has no broad Windows ACL entry.",
    )


def production_preflight(
    settings: Settings | None = None,
    *,
    require_worker_heartbeat: bool = True,
) -> ProductionPreflight:
    """Run non-mutating production deployment checks with safe operator detail."""

    active_settings = settings or get_settings()
    checks: list[ProductionPreflightCheck] = []
    if not active_settings.is_production:
        checks.append(
            ProductionPreflightCheck(
                "production_profile",
                False,
                "ERP_ENV must be production before running a production preflight.",
            )
        )
        return ProductionPreflight(active_settings.env, _now(), tuple(checks))

    checks.extend(_database_checks(active_settings))
    checks.append(_backup_tool_check())
    checks.extend(
        [
            _path_writable_check("media_storage", active_settings.media_upload_dir),
            _path_writable_check("log_storage", active_settings.log_dir),
            _path_writable_check("diagnostics_storage", active_settings.support_diagnostics_dir),
            _path_writable_check("postgres_backup_storage", active_settings.postgres_backup_dir),
            _env_file_check(),
        ]
    )
    heartbeat_check = _worker_heartbeat_check(active_settings)
    if not require_worker_heartbeat:
        heartbeat_check = ProductionPreflightCheck(
            heartbeat_check.name,
            heartbeat_check.ok,
            heartbeat_check.detail,
            required=False,
        )
    checks.append(heartbeat_check)
    return ProductionPreflight(active_settings.env, _now(), tuple(checks))


def assert_production_runtime_ready(settings: Settings | None = None) -> ProductionPreflight:
    """Block a production API start if database/storage/release checks fail.

    Worker liveness is intentionally checked by the post-start release preflight;
    requiring it here would make first service startup impossible.
    """

    active_settings = settings or get_settings()
    if not active_settings.is_production:
        return ProductionPreflight(active_settings.env, _now(), tuple())
    preflight = production_preflight(active_settings, require_worker_heartbeat=False)
    failed = [check for check in preflight.checks if check.required and not check.ok]
    if failed:
        detail = "; ".join(f"{check.name}: {check.detail}" for check in failed)
        raise RuntimeError(f"Production preflight failed. {detail}")
    return preflight
