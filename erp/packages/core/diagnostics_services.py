from __future__ import annotations

import json
import platform
import zipfile
from dataclasses import asdict, dataclass
from datetime import datetime
from functools import lru_cache
from io import BytesIO
from pathlib import Path
from typing import Any

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import inspect, text
from sqlalchemy.orm import Session

from erp import __version__
from erp.packages.core.config import Settings, get_settings
from erp.packages.core.modules.manifest import load_module_manifests
from erp.packages.core.services import record_audit, utcnow

SECRET_MARKERS = ("secret", "password", "token", "key", "credential")
REQUIRED_RUNTIME_TABLES = frozenset(
    {
        "ledger_accounts",
        "ledger_periods",
        "ledger_journals",
        "ledger_lines",
        "vendor_inventory_balances",
        "vendor_inventory_movements",
    }
)


@dataclass(frozen=True)
class DiagnosticsSummary:
    app_version: str
    environment: str
    database_driver: str
    migration_revision: str | None
    expected_migration_revision: str | None
    database_ready: bool
    company_id: str | None
    module_count: int
    settings: dict[str, object]
    runtime: dict[str, object]
    generated_at: datetime


def redact_settings(settings: Settings) -> dict[str, object]:
    redacted: dict[str, object] = {}
    for name, value in settings.model_dump().items():
        if any(marker in name.lower() for marker in SECRET_MARKERS):
            redacted[name] = "***REDACTED***"
        elif name.lower().endswith("url") and "database" in name.lower():
            redacted[name] = "***REDACTED***"
        else:
            redacted[name] = value
    return redacted


def current_migration_revision(db: Session) -> str | None:
    inspector = inspect(db.get_bind())
    if "alembic_version" not in inspector.get_table_names():
        return None
    try:
        return db.scalar(text("select version_num from alembic_version"))
    except Exception:
        return None


@lru_cache
def expected_migration_revision() -> str | None:
    try:
        root = Path(__file__).resolve().parents[3]
        cfg = Config(str(root / "alembic.ini"))
        cfg.set_main_option("script_location", str(root / "migrations"))
        return ScriptDirectory.from_config(cfg).get_current_head()
    except Exception:
        return None


def missing_required_runtime_tables(bind: object) -> tuple[str, ...]:
    existing = set(inspect(bind).get_table_names())
    return tuple(sorted(REQUIRED_RUNTIME_TABLES - existing))


def is_database_migration_current(db: Session) -> bool:
    current = current_migration_revision(db)
    expected = expected_migration_revision()
    return (
        current is not None
        and expected is not None
        and current == expected
        and not missing_required_runtime_tables(db.get_bind())
    )


def diagnostics_runtime_health(db: Session, company_id: str | None) -> dict[str, object]:
    """Return bounded operational state without exposing connection secrets."""
    from erp.packages.core.production_services import read_worker_heartbeat
    from erp.packages.core.woocommerce_services import (
        woocommerce_sync_job_status,
        woocommerce_sync_outbox_status,
    )

    worker = read_worker_heartbeat() or {"status": "missing"}
    if company_id is None:
        return {
            "worker": worker,
            "woocommerce_jobs": {},
            "woocommerce_outbox": {},
        }
    return {
        "worker": worker,
        "woocommerce_jobs": woocommerce_sync_job_status(db, company_id),
        "woocommerce_outbox": woocommerce_sync_outbox_status(db, company_id),
    }


def diagnostics_summary(db: Session, company_id: str | None) -> DiagnosticsSummary:
    settings = get_settings()
    bind = db.get_bind()
    current_revision = current_migration_revision(db)
    expected_revision = expected_migration_revision()
    return DiagnosticsSummary(
        app_version=__version__,
        environment=settings.env,
        database_driver=bind.url.drivername,
        migration_revision=current_revision,
        expected_migration_revision=expected_revision,
        database_ready=is_database_migration_current(db),
        company_id=company_id,
        module_count=len(load_module_manifests()),
        settings=redact_settings(settings),
        runtime=diagnostics_runtime_health(db, company_id),
        generated_at=utcnow(),
    )


def diagnostics_payload(db: Session, company_id: str | None) -> dict[str, Any]:
    summary = diagnostics_summary(db, company_id)
    modules = [manifest.summary() for manifest in load_module_manifests()]
    return {
        "summary": asdict(summary),
        "modules": modules,
        "python": {
            "version": platform.python_version(),
            "platform": platform.platform(),
        },
    }


def create_diagnostics_zip(
    db: Session,
    *,
    company_id: str | None,
    user_id: str,
) -> tuple[str, bytes]:
    payload = diagnostics_payload(db, company_id)
    generated_at = utcnow()
    filename = f"erp-diagnostics-{generated_at:%Y%m%d-%H%M%S}.zip"

    buffer = BytesIO()
    with zipfile.ZipFile(buffer, mode="w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            "diagnostics.json",
            json.dumps(payload, indent=2, default=str),
        )
        archive.writestr(
            "README.txt",
            (
                "Enterprise Commerce ERP diagnostics export.\n"
                "Secrets are redacted. Runtime databases, logs, auth caches, "
                "and customer documents are not included.\n"
            ),
        )
    record_audit(
        db,
        action="support.diagnostics_exported",
        company_id=company_id,
        user_id=user_id,
        entity_type="diagnostics",
        entity_id=filename,
        metadata={"filename": filename},
    )
    return filename, buffer.getvalue()


def diagnostics_dir() -> Path:
    path = Path(get_settings().support_diagnostics_dir)
    path.mkdir(parents=True, exist_ok=True)
    return path
