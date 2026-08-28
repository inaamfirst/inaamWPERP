from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker

from erp.apps.license_server.main import create_app
from erp.packages.core.config import get_settings
from erp.packages.core.db.base import Base
from erp.packages.core.db.models import LicenseServerEvent, LicenseServerRecord


def license_session_factory(tmp_path: Path) -> sessionmaker[Session]:
    engine = create_engine(
        f"sqlite:///{tmp_path / 'license-server.db'}",
        connect_args={"check_same_thread": False},
        future=True,
    )
    Base.metadata.create_all(
        engine,
        tables=[
            Base.metadata.tables["license_server_records"],
            Base.metadata.tables["license_server_events"],
        ],
    )
    return sessionmaker(bind=engine, expire_on_commit=False, future=True)


def test_license_server_state_survives_app_restart(tmp_path: Path) -> None:
    session_factory = license_session_factory(tmp_path)
    settings = get_settings()
    first_client = TestClient(
        create_app(settings=settings, session_factory=session_factory)
    )

    health = first_client.get("/license/v1/health")
    assert health.status_code == 200
    activation = first_client.post(
        "/license/v1/licenses/activate",
        json={
            "license_key": "retail-license-12345",
            "company_id": "company-1",
            "company_name": "Retail Company",
            "device_id": "device-1",
            "plan": "enterprise",
        },
    )
    assert activation.status_code == 200
    activated = activation.json()
    assert activated["status"] == "active"
    assert activated["plan"] == "enterprise"
    assert "retail-license-12345" not in json.dumps(activated)

    # A new FastAPI application represents a process restart while retaining
    # the same durable database.
    restarted_client = TestClient(
        create_app(settings=settings, session_factory=session_factory)
    )
    validation = restarted_client.post(
        "/license/v1/licenses/validate",
        json={
            "license_key_hash": activated["license_key_hash"],
            "device_id": "device-1",
        },
    )
    assert validation.status_code == 200
    assert validation.json()["license_id"] == activated["license_id"]

    repeated = restarted_client.post(
        "/license/v1/licenses/activate",
        json={
            "license_key": "retail-license-12345",
            "company_id": "company-1",
            "company_name": "Retail Company",
            "device_id": "device-1",
            "plan": "enterprise",
        },
    )
    assert repeated.status_code == 200
    assert repeated.json()["license_id"] == activated["license_id"]

    wrong_device = restarted_client.post(
        "/license/v1/licenses/validate",
        json={
            "license_key_hash": activated["license_key_hash"],
            "device_id": "device-2",
        },
    )
    assert wrong_device.status_code == 403

    denied_revoke = restarted_client.post(
        "/license/v1/licenses/revoke",
        json={"license_id": activated["license_id"], "reason": "test"},
    )
    assert denied_revoke.status_code == 401

    revoked = restarted_client.post(
        "/license/v1/licenses/revoke",
        headers={"X-License-Admin-Key": settings.license_server_admin_key},
        json={"license_id": activated["license_id"], "reason": "test"},
    )
    assert revoked.status_code == 200
    assert revoked.json()["status"] == "revoked"

    renewed = restarted_client.post(
        "/license/v1/licenses/renew",
        headers={"X-License-Admin-Key": settings.license_server_admin_key},
        json={"license_id": activated["license_id"], "extend_days": 30},
    )
    assert renewed.status_code == 200
    assert renewed.json()["status"] == "active"
    assert renewed.json()["expires_at"] != activated["expires_at"]

    with session_factory() as db:
        assert db.scalar(select(func.count(LicenseServerRecord.id))) == 1
        assert db.scalar(select(func.count(LicenseServerEvent.id))) == 3


def test_license_server_disables_docs_in_production_settings(tmp_path: Path) -> None:
    session_factory = license_session_factory(tmp_path)
    production_settings = get_settings().model_copy(
        update={"env": "production", "docs_enabled": None}
    )
    client = TestClient(
        create_app(settings=production_settings, session_factory=session_factory)
    )

    assert client.get("/docs").status_code == 404
    assert client.get("/redoc").status_code == 404
