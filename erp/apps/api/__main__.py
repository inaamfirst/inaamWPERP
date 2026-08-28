from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import uvicorn
from alembic import command
from alembic.config import Config

from erp.packages.core.config import Settings, get_settings
from erp.packages.core.production_services import (
    assert_production_runtime_ready,
    production_preflight,
)


def migration_resource_root() -> Path:
    """Locate Alembic data in source trees and PyInstaller distributions."""

    frozen_root = getattr(sys, "_MEIPASS", None)
    if frozen_root:
        return Path(frozen_root)
    return Path(__file__).resolve().parents[3]


def migrate_database(settings: Settings) -> None:
    root = migration_resource_root()
    config_path = root / "alembic.ini"
    migrations_path = root / "migrations"
    if not config_path.is_file() or not migrations_path.is_dir():
        raise RuntimeError("Bundled Alembic migration files are missing.")
    config = Config(str(config_path))
    config.set_main_option("script_location", str(migrations_path))
    config.set_main_option("prepend_sys_path", str(root))
    config.set_main_option("sqlalchemy.url", settings.database_url.replace("%", "%%"))
    command.upgrade(config, "head")


def main() -> None:
    settings = get_settings()
    if os.environ.get("ERP_MIGRATE_ONLY") == "1":
        migrate_database(settings)
        return
    if os.environ.get("ERP_PREFLIGHT_ONLY") == "1":
        preflight = production_preflight(
            settings,
            require_worker_heartbeat=(
                os.environ.get("ERP_PREFLIGHT_SKIP_WORKER_HEARTBEAT") != "1"
            ),
        )
        print(json.dumps(preflight.as_dict(), indent=2, sort_keys=True))
        if not preflight.ok:
            raise SystemExit(1)
        return

    assert_production_runtime_ready(settings)
    uvicorn.run(
        "erp.apps.api.main:app",
        host=settings.api_host,
        port=settings.api_port,
        reload=False,
    )


if __name__ == "__main__":
    main()
