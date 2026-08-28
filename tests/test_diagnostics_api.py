from __future__ import annotations

import json
import zipfile
from collections.abc import Iterator
from io import BytesIO
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from erp.apps.api.main import create_app
from erp.packages.core.db.base import Base
from erp.packages.core.db.models import AuditLog
from erp.packages.core.db.session import get_session


@pytest.fixture()
def client(tmp_path: Path) -> Iterator[TestClient]:
    engine = create_engine(
        f"sqlite:///{tmp_path / 'diagnostics_api.db'}",
        connect_args={"check_same_thread": False},
        future=True,
    )
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(
        bind=engine,
        autoflush=False,
        autocommit=False,
        expire_on_commit=False,
        future=True,
    )

    def override_session() -> Iterator[Session]:
        session = session_factory()
        try:
            yield session
        finally:
            session.close()

    app = create_app()
    app.dependency_overrides[get_session] = override_session
    with TestClient(app) as test_client:
        test_client.session_factory = session_factory  # type: ignore[attr-defined]
        yield test_client
    app.dependency_overrides.clear()
    engine.dispose()


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def complete_first_use_setup(client: TestClient) -> tuple[str, str]:
    response = client.post(
        "/api/v1/setup/first-use",
        json={
            "company_name": "Diagnostics Test Company",
            "username": "admin",
            "password": "admin12345",
            "full_name": "Admin User",
            "email": "admin@example.com",
        },
    )
    assert response.status_code == 200
    payload = response.json()
    return str(payload["access_token"]), str(payload["company"]["id"])


def test_diagnostics_summary_redacts_secrets(client: TestClient) -> None:
    token, _company_id = complete_first_use_setup(client)

    response = client.get("/api/v1/support/diagnostics", headers=bearer(token))
    assert response.status_code == 200
    payload = response.json()

    settings = payload["settings"]
    assert settings["secret_key"] == "***REDACTED***"
    assert settings["license_server_admin_key"] == "***REDACTED***"
    assert settings["license_offline_signing_key"] == "***REDACTED***"
    assert settings["database_url"] == "***REDACTED***"
    assert payload["module_count"] == 17
    runtime = payload["runtime"]
    assert set(runtime) == {"worker", "woocommerce_jobs", "woocommerce_outbox"}
    assert runtime["worker"]
    assert "pending_media_pushes" in runtime["woocommerce_outbox"]


def test_diagnostics_zip_excludes_sensitive_files_and_records_audit(client: TestClient) -> None:
    token, company_id = complete_first_use_setup(client)

    response = client.get("/api/v1/support/diagnostics.zip", headers=bearer(token))
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/zip"

    with zipfile.ZipFile(BytesIO(response.content)) as archive:
        names = set(archive.namelist())
        assert names == {"README.txt", "diagnostics.json"}
        payload = json.loads(archive.read("diagnostics.json").decode("utf-8"))

    serialized = json.dumps(payload)
    assert "dev-only-change-me" not in serialized
    assert ".env" not in names
    assert not any(name.endswith((".db", ".sqlite", ".sqlite3")) for name in names)

    session_factory = client.session_factory  # type: ignore[attr-defined]
    with session_factory() as db:
        logs = db.scalars(
            select(AuditLog).where(
                AuditLog.company_id == company_id,
                AuditLog.action == "support.diagnostics_exported",
            )
        ).all()
        assert len(logs) == 1
