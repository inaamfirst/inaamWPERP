from __future__ import annotations

from pathlib import Path

import pytest

from erp.packages.core import production_services
from erp.packages.core.config import Settings


def production_settings(tmp_path: Path) -> Settings:
    return Settings(
        env="production",
        database_url="postgresql+psycopg://erp_app:strong-password@db.example.test:5432/erp",
        api_base_url="https://erp.example.test",
        secret_key="real-secret-key",
        bootstrap_token="production-bootstrap-token-for-service-tests",
        license_server_admin_key="release-admin-key",
        license_offline_signing_key="release-signing-key",
        trusted_hosts=["erp.example.test"],
        trusted_proxy_ips=["127.0.0.1"],
        force_https=True,
        worker_loop=True,
        media_upload_dir=str(tmp_path / "media"),
        log_dir=str(tmp_path / "logs"),
        support_diagnostics_dir=str(tmp_path / "diagnostics"),
        postgres_backup_dir=str(tmp_path / "backups"),
        worker_heartbeat_file=str(tmp_path / "worker" / "heartbeat.json"),
    )


def test_worker_heartbeat_is_atomically_published_and_read(tmp_path: Path) -> None:
    settings = production_settings(tmp_path)

    assert production_services.write_worker_heartbeat(
        worker_id="test-worker:1",
        status="idle",
        settings=settings,
    )
    payload = production_services.read_worker_heartbeat(settings)

    assert payload is not None
    assert payload["worker_id"] == "test-worker:1"
    assert payload["status"] == "idle"
    assert payload["run_id"] is None
    check = production_services._worker_heartbeat_check(settings)
    assert check.ok is True


def test_production_preflight_combines_runtime_checks_without_connecting_live_db(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    settings = production_settings(tmp_path)
    assert production_services.write_worker_heartbeat(
        worker_id="test-worker:1",
        status="idle",
        settings=settings,
    )
    monkeypatch.setattr(
        production_services,
        "_database_checks",
        lambda _settings: [
            production_services.ProductionPreflightCheck(
                "postgresql_connection", True, "simulated database is reachable"
            ),
            production_services.ProductionPreflightCheck(
                "database_migrations", True, "simulated migration is current"
            ),
        ],
    )
    monkeypatch.setattr(
        production_services,
        "_backup_tool_check",
        lambda: production_services.ProductionPreflightCheck(
            "postgres_backup_tool", True, "simulated pg_dump"
        ),
    )
    monkeypatch.setattr(
        production_services,
        "_env_file_check",
        lambda: production_services.ProductionPreflightCheck(
            "environment_file_permissions", True, "simulated restricted file"
        ),
    )

    result = production_services.production_preflight(settings)

    assert result.ok is True
    assert {check.name for check in result.checks} >= {
        "postgresql_connection",
        "database_migrations",
        "postgres_backup_tool",
        "media_storage",
        "log_storage",
        "diagnostics_storage",
        "postgres_backup_storage",
        "worker_heartbeat",
    }
    assert production_services.assert_production_runtime_ready(settings).ok is True


def test_production_preflight_reports_missing_worker_without_blocking_api_start(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    settings = production_settings(tmp_path)
    monkeypatch.setattr(
        production_services,
        "_database_checks",
        lambda _settings: [production_services.ProductionPreflightCheck("database", True, "ok")],
    )
    monkeypatch.setattr(
        production_services,
        "_backup_tool_check",
        lambda: production_services.ProductionPreflightCheck("postgres_backup_tool", True, "ok"),
    )
    monkeypatch.setattr(
        production_services,
        "_env_file_check",
        lambda: production_services.ProductionPreflightCheck(
            "environment_file_permissions", True, "ok"
        ),
    )

    full = production_services.production_preflight(settings)
    assert full.ok is False
    assert next(check for check in full.checks if check.name == "worker_heartbeat").required

    startup = production_services.assert_production_runtime_ready(settings)
    worker_check = next(check for check in startup.checks if check.name == "worker_heartbeat")
    assert startup.ok is True
    assert worker_check.required is False
