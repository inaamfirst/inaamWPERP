from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from erp.apps.api.main import create_app
from erp.packages.core.db.base import Base
from erp.packages.core.db.models import (
    Company,
    Permission,
    Role,
    RolePermission,
    User,
    UserRole,
    new_uuid,
)
from erp.packages.core.db.session import get_session
from erp.packages.core.security import hash_password
from erp.packages.core.services import declared_permissions, issue_session


@dataclass(frozen=True)
class ApiHarness:
    client: TestClient
    session_factory: sessionmaker


@pytest.fixture()
def harness(tmp_path: Path) -> Iterator[ApiHarness]:
    engine = create_engine(
        f"sqlite:///{tmp_path / 'whatsapp_api.db'}",
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
        yield ApiHarness(client=test_client, session_factory=session_factory)
    app.dependency_overrides.clear()
    engine.dispose()


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def complete_first_use_setup(client: TestClient) -> str:
    response = client.post(
        "/api/v1/setup/first-use",
        json={
            "company_name": "WhatsApp Test Company",
            "username": "admin",
            "password": "admin12345",
            "full_name": "Admin User",
            "email": "whatsapp-admin@example.com",
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert "whatsapp.send" in payload["permissions"]
    return str(payload["access_token"])


def create_second_tenant_token(harness: ApiHarness) -> str:
    with harness.session_factory() as db:
        company_id = new_uuid()
        user_id = new_uuid()
        role_id = new_uuid()
        company = Company(id=company_id, name="Second WhatsApp Company", status="active")
        user = User(
            id=user_id,
            company_id=company_id,
            username="tenant_two_admin",
            email="whatsapp-tenant-two@example.com",
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
        return issued.token


def test_whatsapp_templates_queue_mock_delivery_and_tenant_isolation(
    harness: ApiHarness,
) -> None:
    client = harness.client
    assert client.get("/api/v1/whatsapp/messages").status_code == 401

    token = complete_first_use_setup(client)
    headers = bearer(token)

    template = client.post(
        "/api/v1/whatsapp/templates",
        headers=headers,
        json={"name": "order_update", "body": "Hello {name}, order {order_no} is ready."},
    )
    assert template.status_code == 201
    template_id = template.json()["id"]

    duplicate_template = client.post(
        "/api/v1/whatsapp/templates",
        headers=headers,
        json={"name": "order_update", "body": "Duplicate"},
    )
    assert duplicate_template.status_code == 409

    missing_variable = client.post(
        "/api/v1/whatsapp/messages",
        headers=headers,
        json={
            "recipient_phone": "+923001234567",
            "template_id": template_id,
            "variables": {"name": "Sara"},
        },
    )
    assert missing_variable.status_code == 422

    invalid_phone = client.post(
        "/api/v1/whatsapp/messages",
        headers=headers,
        json={"recipient_phone": "bad", "body": "Hello"},
    )
    assert invalid_phone.status_code == 422

    queued = client.post(
        "/api/v1/whatsapp/messages",
        headers=headers,
        json={
            "recipient_phone": "+923001234567",
            "template_id": template_id,
            "variables": {"name": "Sara", "order_no": "1001"},
            "idempotency_key": "wa:test:1001",
        },
    )
    assert queued.status_code == 200
    queued_payload = queued.json()
    message_id = queued_payload["id"]
    assert queued_payload["message_body"] == "Hello Sara, order 1001 is ready."

    duplicate_queue = client.post(
        "/api/v1/whatsapp/messages",
        headers=headers,
        json={
            "recipient_phone": "+923001234567",
            "template_id": template_id,
            "variables": {"name": "Sara", "order_no": "1001"},
            "idempotency_key": "wa:test:1001",
        },
    )
    assert duplicate_queue.status_code == 200
    assert duplicate_queue.json()["id"] == message_id

    failure = client.post(
        f"/api/v1/whatsapp/messages/{message_id}/mock-send",
        headers=headers,
        json={"force_failure": True},
    )
    assert failure.status_code == 200
    assert failure.json()["status"] == "failed"
    assert "forced failure" in failure.json()["error"]

    failed_messages = client.get("/api/v1/whatsapp/messages?status=failed", headers=headers)
    assert failed_messages.status_code == 200
    assert failed_messages.json()[0]["last_error"] == "Mock WhatsApp adapter forced failure."

    logs = client.get(
        f"/api/v1/whatsapp/messages/{message_id}/delivery-logs",
        headers=headers,
    )
    assert logs.status_code == 200
    assert logs.json()[0]["adapter"] == "mock-local"

    plain_message = client.post(
        "/api/v1/whatsapp/messages",
        headers=headers,
        json={
            "recipient_phone": "+923009999999",
            "body": "Manual hello {name}",
            "variables": {"name": "Ali"},
        },
    )
    assert plain_message.status_code == 200
    success = client.post(
        f"/api/v1/whatsapp/messages/{plain_message.json()['id']}/mock-send",
        headers=headers,
        json={"force_failure": False},
    )
    assert success.status_code == 200
    assert success.json()["status"] == "sent"
    assert success.json()["provider_message_id"].startswith("mock-")

    tenant_two_token = create_second_tenant_token(harness)
    tenant_two_headers = bearer(tenant_two_token)
    assert client.get("/api/v1/whatsapp/messages", headers=tenant_two_headers).json() == []
    tenant_two_send = client.post(
        f"/api/v1/whatsapp/messages/{message_id}/mock-send",
        headers=tenant_two_headers,
        json={"force_failure": False},
    )
    assert tenant_two_send.status_code == 404

    audit_logs = client.get("/api/v1/audit-logs", headers=headers)
    actions = {entry["action"] for entry in audit_logs.json()}
    assert {
        "whatsapp.template_created",
        "whatsapp.message_queued",
        "whatsapp.message_failed",
        "whatsapp.message_sent",
    }.issubset(actions)
