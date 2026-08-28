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
        f"sqlite:///{tmp_path / 'orders_api.db'}",
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
            "company_name": "Orders Test Company",
            "username": "admin",
            "password": "admin12345",
            "full_name": "Admin User",
            "email": "orders-admin@example.com",
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert "orders.manage" in payload["permissions"]
    return str(payload["access_token"])


def create_second_tenant_token(harness: ApiHarness) -> str:
    with harness.session_factory() as db:
        company_id = new_uuid()
        user_id = new_uuid()
        role_id = new_uuid()
        company = Company(id=company_id, name="Second Orders Company", status="active")
        user = User(
            id=user_id,
            company_id=company_id,
            username="tenant_two_admin",
            email="orders-tenant-two@example.com",
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


def create_customer(client: TestClient, headers: dict[str, str]) -> str:
    response = client.post(
        "/api/v1/customers",
        headers=headers,
        json={"full_name": "Order Customer", "phone": "+923001111111"},
    )
    assert response.status_code == 201
    return str(response.json()["id"])


def create_order_product(client: TestClient, headers: dict[str, str]) -> tuple[str, str]:
    response = client.post(
        "/api/v1/catalog/products",
        headers=headers,
        json={
            "name": "Order Product",
            "slug": "order-product",
            "sku": "ORDER-BASE",
            "product_type": "variable",
            "variants": [
                {
                    "name": "Standard",
                    "sku": "ORDER-STD",
                    "price_minor": 50000,
                    "currency": "PKR",
                }
            ],
        },
    )
    assert response.status_code == 201
    payload = response.json()
    return str(payload["id"]), str(payload["variants"][0]["id"])


def test_order_creation_status_payments_auth_and_tenant_isolation(
    harness: ApiHarness,
) -> None:
    client = harness.client
    assert client.get("/api/v1/orders").status_code == 401

    token = complete_first_use_setup(client)
    headers = bearer(token)
    customer_id = create_customer(client, headers)
    product_id, variant_id = create_order_product(client, headers)

    invalid_order = client.post(
        "/api/v1/orders",
        headers=headers,
        json={"customer_id": customer_id, "items": []},
    )
    assert invalid_order.status_code == 422

    order = client.post(
        "/api/v1/orders",
        headers=headers,
        json={
            "customer_id": customer_id,
            "discount_minor": 10000,
            "shipping_minor": 5000,
            "items": [
                {
                    "product_id": product_id,
                    "variant_id": variant_id,
                    "quantity": 2,
                }
            ],
        },
    )
    assert order.status_code == 201
    order_payload = order.json()
    order_id = order_payload["id"]
    assert order_payload["status"] == "pending"
    assert order_payload["subtotal_minor"] == 100000
    assert order_payload["total_minor"] == 95000
    assert order_payload["items"][0]["sku"] == "ORDER-STD"
    assert order_payload["status_history"][0]["to_status"] == "pending"

    pending_orders = client.get("/api/v1/orders?status=pending", headers=headers)
    assert pending_orders.status_code == 200
    assert pending_orders.json()[0]["id"] == order_id

    invalid_transition = client.post(
        f"/api/v1/orders/{order_id}/status",
        headers=headers,
        json={"status": "delivered"},
    )
    assert invalid_transition.status_code == 409

    confirmed = client.post(
        f"/api/v1/orders/{order_id}/status",
        headers=headers,
        json={"status": "confirmed", "reason": "Customer confirmed."},
    )
    assert confirmed.status_code == 200
    assert confirmed.json()["status"] == "confirmed"

    payment = client.post(
        f"/api/v1/orders/{order_id}/payments",
        headers=headers,
        json={"amount_minor": 50000, "method": "cash", "reference": "RCPT-1"},
    )
    assert payment.status_code == 201
    assert payment.json()["amount_minor"] == 50000

    partially_paid_order = client.get(f"/api/v1/orders/{order_id}", headers=headers)
    assert partially_paid_order.status_code == 200
    assert partially_paid_order.json()["payment_status"] == "partial"
    assert partially_paid_order.json()["paid_minor"] == 50000

    overpayment = client.post(
        f"/api/v1/orders/{order_id}/payments",
        headers=headers,
        json={"amount_minor": 999999, "method": "cash"},
    )
    assert overpayment.status_code == 409

    final_payment = client.post(
        f"/api/v1/orders/{order_id}/payments",
        headers=headers,
        json={"amount_minor": 45000, "method": "cash", "reference": "RCPT-2"},
    )
    assert final_payment.status_code == 201
    paid_order = client.get(f"/api/v1/orders/{order_id}", headers=headers)
    assert paid_order.json()["payment_status"] == "paid"
    assert len(paid_order.json()["payments"]) == 2

    tenant_two_token = create_second_tenant_token(harness)
    tenant_two_headers = bearer(tenant_two_token)
    assert client.get(f"/api/v1/orders/{order_id}", headers=tenant_two_headers).status_code == 404
    assert client.get("/api/v1/orders", headers=tenant_two_headers).json() == []

    tenant_two_order = client.post(
        "/api/v1/orders",
        headers=tenant_two_headers,
        json={
            "customer_id": customer_id,
            "items": [{"product_id": product_id, "variant_id": variant_id, "quantity": 1}],
        },
    )
    assert tenant_two_order.status_code == 404

    audit_logs = client.get("/api/v1/audit-logs", headers=headers)
    actions = {entry["action"] for entry in audit_logs.json()}
    assert {
        "orders.order_created",
        "orders.status_changed",
        "orders.payment_recorded",
    }.issubset(actions)
