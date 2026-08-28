from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from sqlalchemy.orm import Session

from erp.packages.core.catalog_services import require_company_id
from erp.packages.core.db.models import new_uuid
from erp.packages.core.services import ServiceError, record_audit, utcnow


@dataclass(frozen=True)
class BackupMetadata:
    backup_id: str
    database_url_driver: str
    source_path: str
    backup_path: str
    metadata_path: str
    size_bytes: int
    created_at: datetime


@dataclass(frozen=True)
class RestorePlan:
    safe_to_restore: bool
    backup_path: str
    size_bytes: int | None
    strategy: str
    requires_confirmation: bool
    detail: str


def backup_root() -> Path:
    return Path("runtime_data") / "backups"


def sqlite_database_path(db: Session) -> Path:
    bind = db.get_bind()
    url = bind.url
    if url.drivername not in {"sqlite", "sqlite+pysqlite"}:
        raise ServiceError(
            409,
            "Automated V1 backup supports SQLite/dev databases only. Use pg_dump for PostgreSQL.",
        )
    database = url.database
    if not database or database == ":memory:":
        raise ServiceError(409, "In-memory SQLite databases cannot be backed up.")
    path = Path(database).expanduser().resolve()
    if not path.exists():
        raise ServiceError(404, "SQLite database file was not found.")
    return path


def create_sqlite_backup(
    db: Session,
    *,
    company_id: str | None,
    user_id: str,
) -> BackupMetadata:
    scoped_company_id = require_company_id(company_id)
    source = sqlite_database_path(db)
    created_at = utcnow()
    backup_id = new_uuid()
    target_dir = backup_root()
    target_dir.mkdir(parents=True, exist_ok=True)
    backup_path = target_dir / f"erp-sqlite-{created_at:%Y%m%d-%H%M%S}-{backup_id}.db"
    metadata_path = backup_path.with_suffix(".json")

    shutil.copy2(source, backup_path)
    size_bytes = backup_path.stat().st_size
    metadata = {
        "backup_id": backup_id,
        "database_url_driver": "sqlite",
        "source_path": str(source),
        "backup_path": str(backup_path),
        "size_bytes": size_bytes,
        "created_at": created_at.isoformat(),
        "company_id": scoped_company_id,
    }
    metadata_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    record_audit(
        db,
        action="backup.created",
        company_id=scoped_company_id,
        user_id=user_id,
        entity_type="backup",
        entity_id=backup_id,
        metadata={"backup_path": str(backup_path), "size_bytes": size_bytes},
    )
    return BackupMetadata(
        backup_id=backup_id,
        database_url_driver="sqlite",
        source_path=str(source),
        backup_path=str(backup_path),
        metadata_path=str(metadata_path),
        size_bytes=size_bytes,
        created_at=created_at,
    )


def build_restore_plan(backup_path: str) -> RestorePlan:
    path = Path(backup_path).expanduser().resolve()
    if not path.exists():
        return RestorePlan(
            safe_to_restore=False,
            backup_path=str(path),
            size_bytes=None,
            strategy="manual_restore_only",
            requires_confirmation=True,
            detail="Backup file does not exist.",
        )
    if path.suffix.lower() not in {".db", ".sqlite", ".sqlite3"}:
        return RestorePlan(
            safe_to_restore=False,
            backup_path=str(path),
            size_bytes=path.stat().st_size,
            strategy="manual_restore_only",
            requires_confirmation=True,
            detail="Unsupported backup file type for SQLite restore.",
        )
    return RestorePlan(
        safe_to_restore=True,
        backup_path=str(path),
        size_bytes=path.stat().st_size,
        strategy="manual_restore_only",
        requires_confirmation=True,
        detail=(
            "V1 does not overwrite live data. Stop the app, verify the backup, "
            "and restore manually with explicit operator approval."
        ),
    )
