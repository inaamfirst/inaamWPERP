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
        f"sqlite:///{tmp_path / 'admin_api.db'}",
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


def complete_first_use_setup(client: TestClient) -> tuple[str, str]:
    response = client.post(
        "/api/v1/setup/first-use",
        json={
            "company_name": "Admin Test Company",
            "username": "admin",
            "password": "admin12345",
            "full_name": "Admin User",
            "email": "admin@example.com",
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert "tenancy.manage_companies" in payload["permissions"]
    assert "support.view_diagnostics" in payload["permissions"]
    return str(payload["access_token"]), str(payload["company"]["id"])


def create_second_tenant_token(harness: ApiHarness) -> tuple[str, str]:
    with harness.session_factory() as db:
        company = Company(id=new_uuid(), name="Second Tenant", status="active")
        user = User(
            id=new_uuid(),
            company_id=company.id,
            username="tenant_two_admin",
            email="tenant-two@example.com",
            password_hash=hash_password("admin12345"),
            full_name="Tenant Two Admin",
            is_active=True,
        )
        role = Role(
            id=new_uuid(),
            company_id=company.id,
            name="Administrator",
            description="Second tenant administrator.",
        )
        db.add_all([company, user, role])
        db.flush()

        permission_rows = list(
            db.scalars(select(Permission).where(Permission.key.in_(declared_permissions()))).all()
        )
        db.add(UserRole(user_id=user.id, role_id=role.id))
        db.add_all(
            RolePermission(role_id=role.id, permission_id=permission.id)
            for permission in permission_rows
        )
        issued = issue_session(db, user)
        db.commit()
        return issued.token, company.id


def test_tenant_company_user_role_admin_flow(harness: ApiHarness) -> None:
    client = harness.client
    assert client.get("/api/v1/tenancy/companies").status_code == 401

    token, company_id = complete_first_use_setup(client)
    headers = bearer(token)

    companies = client.get("/api/v1/tenancy/companies", headers=headers)
    assert companies.status_code == 200
    assert [company["id"] for company in companies.json()] == [company_id]

    update_company = client.patch(
        f"/api/v1/tenancy/companies/{company_id}",
        headers=headers,
        json={"name": "Admin Test Company Updated", "legal_name": "Admin Test Legal"},
    )
    assert update_company.status_code == 200
    assert update_company.json()["legal_name"] == "Admin Test Legal"

    suspended = client.patch(
        f"/api/v1/tenancy/companies/{company_id}",
        headers=headers,
        json={"status": "suspended"},
    )
    assert suspended.status_code == 403

    create_company = client.post(
        "/api/v1/tenancy/companies",
        headers=headers,
        json={"name": "Blocked Child Company"},
    )
    assert create_company.status_code == 403

    role_response = client.post(
        "/api/v1/identity/roles",
        headers=headers,
        json={
            "name": "Cashier",
            "description": "Store cashier",
            "permissions": ["catalog.view", "orders.view"],
        },
    )
    assert role_response.status_code == 201
    role_payload = role_response.json()
    assert role_payload["permissions"] == ["catalog.view", "orders.view"]

    user_response = client.post(
        "/api/v1/identity/users",
        headers=headers,
        json={
            "username": "cashier",
            "password": "cashier12345",
            "email": "cashier@example.com",
            "full_name": "Cashier User",
            "role_ids": [role_payload["id"]],
        },
    )
    assert user_response.status_code == 201
    user_payload = user_response.json()
    assert user_payload["company_id"] == company_id
    assert user_payload["role_ids"] == [role_payload["id"]]
    assert user_payload["role_names"] == ["Cashier"]

    update_user = client.patch(
        f"/api/v1/identity/users/{user_payload['id']}",
        headers=headers,
        json={"full_name": "Updated Cashier User"},
    )
    assert update_user.status_code == 200
    assert update_user.json()["full_name"] == "Updated Cashier User"

    reset = client.post(
        f"/api/v1/identity/users/{user_payload['id']}/reset-password",
        headers=headers,
        json={"password": "newcashier12345"},
    )
    assert reset.status_code == 200

    login = client.post(
        "/api/v1/auth/login",
        json={"username": "cashier", "password": "newcashier12345"},
    )
    assert login.status_code == 200
    assert login.json()["user"]["username"] == "cashier"

    users = client.get("/api/v1/identity/users", headers=headers)
    assert users.status_code == 200
    assert {user["username"] for user in users.json()} >= {"admin", "cashier"}
    cashier = next(user for user in users.json() if user["username"] == "cashier")
    assert cashier["role_names"] == ["Cashier"]


def test_tenant_admin_cannot_cross_company_boundaries(harness: ApiHarness) -> None:
    client = harness.client
    token_a, company_a = complete_first_use_setup(client)
    headers_a = bearer(token_a)

    token_b, company_b = create_second_tenant_token(harness)
    headers_b = bearer(token_b)

    companies_b = client.get("/api/v1/tenancy/companies", headers=headers_b)
    assert companies_b.status_code == 200
    assert [company["id"] for company in companies_b.json()] == [company_b]

    cross_company_update = client.patch(
        f"/api/v1/tenancy/companies/{company_a}",
        headers=headers_b,
        json={"name": "Illegal Rename"},
    )
    assert cross_company_update.status_code == 403

    users_a = client.get("/api/v1/identity/users", headers=headers_a)
    admin_a_id = users_a.json()[0]["id"]
    cross_user_update = client.patch(
        f"/api/v1/identity/users/{admin_a_id}",
        headers=headers_b,
        json={"full_name": "Illegal Rename"},
    )
    assert cross_user_update.status_code == 404
