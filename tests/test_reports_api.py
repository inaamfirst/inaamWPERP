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
        f"sqlite:///{tmp_path / 'reports_api.db'}",
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
            "company_name": "Reports Test Company",
            "username": "admin",
            "password": "admin12345",
            "full_name": "Admin User",
            "email": "reports-admin@example.com",
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert "reports.view" in payload["permissions"]
    return str(payload["access_token"])


def create_second_tenant_token(harness: ApiHarness) -> str:
    with harness.session_factory() as db:
        company_id = new_uuid()
        user_id = new_uuid()
        role_id = new_uuid()
        company = Company(id=company_id, name="Second Reports Company", status="active")
        user = User(
            id=user_id,
            company_id=company_id,
            username="tenant_two_admin",
            email="reports-tenant-two@example.com",
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


def seed_report_data(client: TestClient, headers: dict[str, str]) -> None:
    customer = client.post(
        "/api/v1/customers",
        headers=headers,
        json={"full_name": "Report Customer", "phone": "+923001212121"},
    )
    assert customer.status_code == 201
    customer_id = customer.json()["id"]

    stocked_product = client.post(
        "/api/v1/catalog/products",
        headers=headers,
        json={
            "name": "Report Product",
            "slug": "report-product",
            "product_type": "variable",
            "variants": [{"name": "Standard", "sku": "REPORT-STD", "price_minor": 50000}],
        },
    )
    assert stocked_product.status_code == 201
    stocked_product_id = stocked_product.json()["id"]
    variant_id = stocked_product.json()["variants"][0]["id"]

    low_stock_product = client.post(
        "/api/v1/catalog/products",
        headers=headers,
        json={"name": "No Stock Product", "slug": "no-stock-product"},
    )
    assert low_stock_product.status_code == 201

    warehouse = client.post(
        "/api/v1/inventory/warehouses",
        headers=headers,
        json={"code": "main", "name": "Main Warehouse"},
    )
    assert warehouse.status_code == 201
    warehouse_id = warehouse.json()["id"]

    stock = client.post(
        "/api/v1/inventory/stock-movements",
        headers=headers,
        json={
            "movement_type": "opening",
            "quantity": 5,
            "warehouse_id": warehouse_id,
            "product_id": stocked_product_id,
            "variant_id": variant_id,
        },
    )
    assert stock.status_code == 201

    order = client.post(
        "/api/v1/orders",
        headers=headers,
        json={
            "customer_id": customer_id,
            "items": [{"product_id": stocked_product_id, "variant_id": variant_id, "quantity": 2}],
        },
    )
    assert order.status_code == 201
    order_id = order.json()["id"]
    assert order.json()["total_minor"] == 100000

    payment = client.post(
        f"/api/v1/orders/{order_id}/payments",
        headers=headers,
        json={"amount_minor": 100000, "method": "cash"},
    )
    assert payment.status_code == 201


def test_reports_dashboard_json_csv_and_tenant_isolation(harness: ApiHarness) -> None:
    client = harness.client
    assert client.get("/api/v1/reports/dashboard-summary").status_code == 401

    token = complete_first_use_setup(client)
    headers = bearer(token)
    seed_report_data(client, headers)

    summary = client.get("/api/v1/reports/dashboard-summary", headers=headers)
    assert summary.status_code == 200
    assert summary.json() == {
        "sales_count": 1,
        "revenue_minor": 100000,
        "pending_orders": 1,
        "low_stock_count": 1,
        "customer_count": 1,
        "product_count": 2,
    }

    sales = client.get("/api/v1/reports/sales", headers=headers)
    assert sales.status_code == 200
    assert sales.json()[0]["status"] == "pending"
    assert sales.json()[0]["revenue_minor"] == 100000

    inventory = client.get("/api/v1/reports/inventory", headers=headers)
    assert inventory.status_code == 200
    assert inventory.json()[0]["quantity_on_hand"] == 5

    customers = client.get("/api/v1/reports/customers", headers=headers)
    assert customers.status_code == 200
    assert customers.json()[0]["full_name"] == "Report Customer"

    orders = client.get("/api/v1/reports/orders", headers=headers)
    assert orders.status_code == 200
    assert orders.json()[0]["payment_status"] == "paid"

    csv_response = client.get("/api/v1/reports/orders.csv", headers=headers)
    assert csv_response.status_code == 200
    assert csv_response.headers["content-type"].startswith("text/csv")
    assert "order_number,customer_id,status,total_minor" in csv_response.text

    tenant_two_token = create_second_tenant_token(harness)
    tenant_two_headers = bearer(tenant_two_token)
    tenant_two_summary = client.get(
        "/api/v1/reports/dashboard-summary",
        headers=tenant_two_headers,
    )
    assert tenant_two_summary.status_code == 200
    assert tenant_two_summary.json() == {
        "sales_count": 0,
        "revenue_minor": 0,
        "pending_orders": 0,
        "low_stock_count": 0,
        "customer_count": 0,
        "product_count": 0,
    }
