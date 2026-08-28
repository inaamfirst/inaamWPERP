from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from erp.apps.api.main import create_app
from erp.packages.core import backup_services, licensing_services
from erp.packages.core.config import get_settings
from erp.packages.core.db.base import Base
from erp.packages.core.db.models import (
    AuditLog,
    Company,
    License,
    Permission,
    Role,
    RolePermission,
    User,
    UserRole,
    new_uuid,
)
from erp.packages.core.db.session import get_session
from erp.packages.core.security import hash_password
from erp.packages.core.services import declared_permissions, issue_session, utcnow


@dataclass(frozen=True)
class ApiHarness:
    client: TestClient
    session_factory: sessionmaker
    db_path: Path
    license_dir: Path


@pytest.fixture()
def harness(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[ApiHarness]:
    db_file = tmp_path / "backup_licensing_test.db"
    backups_dir = tmp_path / "backups"
    license_dir = tmp_path / "licenses"
    monkeypatch.setattr(backup_services, "backup_root", lambda: backups_dir)
    monkeypatch.setattr(
        licensing_services,
        "offline_license_path",
        lambda company_id, settings=None: license_dir / f"{company_id}.license.json",
    )

    engine = create_engine(
        f"sqlite:///{db_file}",
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
        yield ApiHarness(
            client=test_client,
            session_factory=session_factory,
            db_path=db_file,
            license_dir=license_dir,
        )
    app.dependency_overrides.clear()
    engine.dispose()


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def complete_first_use_setup(client: TestClient) -> tuple[str, str]:
    response = client.post(
        "/api/v1/setup/first-use",
        json={
            "company_name": "Backup Licensing Test Co",
            "username": "admin",
            "password": "admin12345",
            "full_name": "Admin User",
            "email": "admin@example.com",
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert "backup.create" in payload["permissions"]
    assert "licensing.manage" in payload["permissions"]
    return str(payload["access_token"]), str(payload["company"]["id"])


def create_second_tenant_token(harness: ApiHarness) -> tuple[str, str]:
    with harness.session_factory() as db:
        company_id = new_uuid()
        user_id = new_uuid()
        role_id = new_uuid()
        company = Company(id=company_id, name="Second Tenant Company", status="active")
        user = User(
            id=user_id,
            company_id=company_id,
            username="tenant_two_admin",
            email="tenant-two@example.com",
            password_hash=hash_password("admin12345"),
            full_name="Tenant Two Admin",
            is_active=True,
        )
        role = Role(
            id=role_id,
            company_id=company_id,
            name="Administrator",
            description="Test tenant administrator.",
        )
        db.add_all([company, user, role])
        db.flush()

        permission_rows = list(
            db.scalars(
                select(Permission).where(Permission.key.in_(declared_permissions()))
            ).all()
        )
        db.add(UserRole(user_id=user.id, role_id=role.id))
        db.add_all(
            RolePermission(role_id=role.id, permission_id=permission.id)
            for permission in permission_rows
        )
        db.flush()
        issued = issue_session(db, user)
        db.commit()
        return issued.token, company_id


def test_backup_and_restore_workflow(harness: ApiHarness) -> None:
    client = harness.client

    # 1. Unauthenticated requests
    assert client.post("/api/v1/backup/sqlite").status_code == 401
    assert (
        client.post(
            "/api/v1/backup/restore-plan",
            json={"backup_path": "fake.db"},
        ).status_code
        == 401
    )

    token, company_id = complete_first_use_setup(client)
    headers = bearer(token)

    # 2. Trigger SQLite Backup (Happy Path)
    response = client.post("/api/v1/backup/sqlite", headers=headers)
    assert response.status_code == 200
    payload = response.json()

    assert "backup_id" in payload
    assert payload["database_url_driver"] == "sqlite"
    assert "backup_path" in payload
    assert "metadata_path" in payload
    assert payload["size_bytes"] > 0
    assert "created_at" in payload

    backup_file = Path(payload["backup_path"])
    metadata_file = Path(payload["metadata_path"])
    assert backup_file.exists()
    assert metadata_file.exists()

    # Verify audit log was recorded for backup creation
    with harness.session_factory() as db:
        logs = db.scalars(
            select(AuditLog)
            .where(AuditLog.company_id == company_id, AuditLog.action == "backup.created")
        ).all()
        assert len(logs) == 1
        assert logs[0].entity_type == "backup"
        assert logs[0].entity_id == payload["backup_id"]

    # 3. Create a restore plan for non-existent file
    plan_response = client.post(
        "/api/v1/backup/restore-plan",
        headers=headers,
        json={"backup_path": "non_existent_file.db"},
    )
    assert plan_response.status_code == 200
    plan_payload = plan_response.json()
    assert plan_payload["safe_to_restore"] is False
    assert "does not exist" in plan_payload["detail"]

    # 4. Create a restore plan for valid SQLite backup file
    plan_response2 = client.post(
        "/api/v1/backup/restore-plan",
        headers=headers,
        json={"backup_path": str(backup_file)},
    )
    assert plan_response2.status_code == 200
    plan_payload2 = plan_response2.json()
    assert plan_payload2["safe_to_restore"] is True
    assert plan_payload2["requires_confirmation"] is True
    assert "manual" in plan_payload2["detail"].lower()


def test_licensing_workflow_and_tenant_isolation(harness: ApiHarness) -> None:
    client = harness.client

    # 1. Unauthenticated requests
    assert client.get("/api/v1/licensing/status").status_code == 401
    assert (
        client.post(
            "/api/v1/licensing/activate",
            json={"license_key": "some-key", "plan": "standard"},
        ).status_code
        == 401
    )

    token_a, company_a = complete_first_use_setup(client)
    headers_a = bearer(token_a)

    # 2. Get initial licensing status (inactive)
    status_resp = client.get("/api/v1/licensing/status", headers=headers_a)
    assert status_resp.status_code == 200
    status_payload = status_resp.json()
    assert status_payload["configured"] is False
    assert status_payload["status"] == "inactive"
    assert status_payload["plan"] is None

    # 3. Validation error: Activate license with invalid plan
    fail_resp = client.post(
        "/api/v1/licensing/activate",
        headers=headers_a,
        json={"license_key": "key12345678", "plan": ""},
    )
    assert fail_resp.status_code == 422

    # 4. Activate license (Happy Path)
    act_resp = client.post(
        "/api/v1/licensing/activate",
        headers=headers_a,
        json={"license_key": "my-secret-license-key", "plan": "enterprise"},
    )
    assert act_resp.status_code == 200
    act_payload = act_resp.json()
    assert act_payload["configured"] is True
    assert act_payload["status"] == "active"
    assert act_payload["plan"] == "enterprise"
    assert act_payload["activated_at"] is not None
    assert act_payload["expires_at"] is not None
    assert act_payload["grace_expires_at"] is not None
    assert act_payload["license_id"] is not None
    assert act_payload["device_id"] == get_settings().license_device_id
    assert act_payload["activation_mode"] == "local_server"

    validate_resp = client.post("/api/v1/licensing/validate", headers=headers_a)
    assert validate_resp.status_code == 200
    assert validate_resp.json()["status"] == "active"

    # Check database and audit log
    with harness.session_factory() as db:
        licenses = db.scalars(
            select(License).where(License.company_id == company_a)
        ).all()
        assert len(licenses) == 1
        assert licenses[0].status == "active"
        assert licenses[0].plan == "enterprise"

        logs = db.scalars(
            select(AuditLog)
            .where(AuditLog.company_id == company_a, AuditLog.action == "licensing.activated")
        ).all()
        assert len(logs) == 1
        assert logs[0].entity_type == "license"
        assert logs[0].entity_id == licenses[0].id
        assert "my-secret-license-key" not in str(licenses[0].metadata_json)

    offline_license = harness.license_dir / f"{company_a}.license.json"
    assert offline_license.exists()
    assert "my-secret-license-key" not in offline_license.read_text(encoding="utf-8")

    with harness.session_factory() as db:
        license_row = db.scalar(select(License).where(License.company_id == company_a))
        assert license_row is not None
        metadata = dict(license_row.metadata_json)
        license_row.expires_at = utcnow() - timedelta(days=1)
        metadata["grace_expires_at"] = (utcnow() + timedelta(days=5)).isoformat()
        license_row.metadata_json = metadata
        db.commit()

    grace_resp = client.post("/api/v1/licensing/validate", headers=headers_a)
    assert grace_resp.status_code == 200
    assert grace_resp.json()["status"] == "grace"

    revoke_resp = client.post(
        "/api/v1/licensing/revoke",
        headers=headers_a,
        json={"reason": "customer cancellation"},
    )
    assert revoke_resp.status_code == 200
    assert revoke_resp.json()["status"] == "revoked"

    validate_revoked_resp = client.post("/api/v1/licensing/validate", headers=headers_a)
    assert validate_revoked_resp.status_code == 200
    assert validate_revoked_resp.json()["status"] == "revoked"

    # 5. Cross-Tenant Isolation: Second company status check should still be inactive
    token_b, company_b = create_second_tenant_token(harness)
    headers_b = bearer(token_b)

    status_resp_b = client.get("/api/v1/licensing/status", headers=headers_b)
    assert status_resp_b.status_code == 200
    assert status_resp_b.json()["configured"] is False
    assert status_resp_b.json()["status"] == "inactive"

    # Activate license for company B
    act_resp_b = client.post(
        "/api/v1/licensing/activate",
        headers=headers_b,
        json={"license_key": "secret-key-tenant-b", "plan": "pro"},
    )
    assert act_resp_b.status_code == 200
    assert act_resp_b.json()["plan"] == "pro"

    # Double check company A license plan is still "enterprise"
    status_resp_a_again = client.get("/api/v1/licensing/status", headers=headers_a)
    assert status_resp_a_again.json()["plan"] == "enterprise"
    assert status_resp_a_again.json()["status"] == "revoked"
