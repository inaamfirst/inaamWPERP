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
        f"sqlite:///{tmp_path / 'inventory_api.db'}",
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
            "company_name": "Inventory Test Company",
            "username": "admin",
            "password": "admin12345",
            "full_name": "Admin User",
            "email": "inventory-admin@example.com",
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert "inventory.manage" in payload["permissions"]
    return str(payload["access_token"])


def create_second_tenant_token(harness: ApiHarness) -> str:
    with harness.session_factory() as db:
        company_id = new_uuid()
        user_id = new_uuid()
        role_id = new_uuid()
        company = Company(id=company_id, name="Second Inventory Company", status="active")
        user = User(
            id=user_id,
            company_id=company_id,
            username="tenant_two_admin",
            email="inventory-tenant-two@example.com",
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


def create_inventory_product(client: TestClient, headers: dict[str, str]) -> tuple[str, str]:
    product = client.post(
        "/api/v1/catalog/products",
        headers=headers,
        json={
            "name": "USB Cable",
            "slug": "usb-cable",
            "sku": "USB-BASE",
            "product_type": "variable",
            "variants": [
                {
                    "name": "1 meter",
                    "sku": "USB-1M",
                    "price_minor": 50000,
                    "currency": "PKR",
                    "attributes": {"length": "1m"},
                }
            ],
        },
    )
    assert product.status_code == 201
    payload = product.json()
    return str(payload["id"]), str(payload["variants"][0]["id"])


def test_inventory_movements_calculation_validation_and_tenant_isolation(
    harness: ApiHarness,
) -> None:
    client = harness.client
    assert client.get("/api/v1/inventory/stock").status_code == 401

    token = complete_first_use_setup(client)
    headers = bearer(token)

    invalid_warehouse = client.post(
        "/api/v1/inventory/warehouses",
        headers=headers,
        json={"code": "x", "name": "Main Warehouse"},
    )
    assert invalid_warehouse.status_code == 422

    warehouse = client.post(
        "/api/v1/inventory/warehouses",
        headers=headers,
        json={"code": "main", "name": "Main Warehouse"},
    )
    assert warehouse.status_code == 201
    warehouse_payload = warehouse.json()
    warehouse_id = warehouse_payload["id"]
    assert warehouse_payload["code"] == "MAIN"

    duplicate_warehouse = client.post(
        "/api/v1/inventory/warehouses",
        headers=headers,
        json={"code": "MAIN", "name": "Duplicate Warehouse"},
    )
    assert duplicate_warehouse.status_code == 409

    product_id, variant_id = create_inventory_product(client, headers)

    movement_payloads = [
        {"movement_type": "opening", "quantity": 10},
        {"movement_type": "stock_out", "quantity": 3},
        {"movement_type": "damaged", "quantity": 2},
        {"movement_type": "adjustment", "quantity_delta": 5},
    ]
    expected_deltas = [10, -3, -2, 5]
    for payload, expected_delta in zip(movement_payloads, expected_deltas, strict=True):
        response = client.post(
            "/api/v1/inventory/stock-movements",
            headers=headers,
            json={
                **payload,
                "warehouse_id": warehouse_id,
                "product_id": product_id,
                "variant_id": variant_id,
                "reason": "Test stock movement",
            },
        )
        assert response.status_code == 201
        assert response.json()["quantity_delta"] == expected_delta

    stock = client.get(
        f"/api/v1/inventory/stock?warehouse_id={warehouse_id}&product_id={product_id}",
        headers=headers,
    )
    assert stock.status_code == 200
    assert stock.json()[0]["quantity_on_hand"] == 10

    invalid_adjustment = client.post(
        "/api/v1/inventory/stock-movements",
        headers=headers,
        json={
            "movement_type": "adjustment",
            "quantity": 1,
            "warehouse_id": warehouse_id,
            "product_id": product_id,
            "variant_id": variant_id,
        },
    )
    assert invalid_adjustment.status_code == 422

    negative_stock = client.post(
        "/api/v1/inventory/stock-movements",
        headers=headers,
        json={
            "movement_type": "stock_out",
            "quantity": 99,
            "warehouse_id": warehouse_id,
            "product_id": product_id,
            "variant_id": variant_id,
        },
    )
    assert negative_stock.status_code == 409

    movement_history = client.get(
        f"/api/v1/inventory/stock-movements?product_id={product_id}",
        headers=headers,
    )
    assert movement_history.status_code == 200
    assert len(movement_history.json()) == 4

    tenant_two_token = create_second_tenant_token(harness)
    tenant_two_headers = bearer(tenant_two_token)
    tenant_two_warehouse = client.get(
        f"/api/v1/inventory/warehouses/{warehouse_id}",
        headers=tenant_two_headers,
    )
    assert tenant_two_warehouse.status_code == 404
    assert client.get("/api/v1/inventory/stock", headers=tenant_two_headers).json() == []

    tenant_two_movement = client.post(
        "/api/v1/inventory/stock-movements",
        headers=tenant_two_headers,
        json={
            "movement_type": "opening",
            "quantity": 1,
            "warehouse_id": warehouse_id,
            "product_id": product_id,
            "variant_id": variant_id,
        },
    )
    assert tenant_two_movement.status_code == 404

    warehouse_update = client.patch(
        f"/api/v1/inventory/warehouses/{warehouse_id}",
        headers=headers,
        json={"name": "Main Stock Room"},
    )
    assert warehouse_update.status_code == 200
    assert warehouse_update.json()["name"] == "Main Stock Room"

    warehouse_delete = client.delete(
        f"/api/v1/inventory/warehouses/{warehouse_id}",
        headers=headers,
    )
    assert warehouse_delete.status_code == 200
    assert client.get("/api/v1/inventory/warehouses", headers=headers).json() == []

    archived_warehouses = client.get(
        "/api/v1/inventory/warehouses?include_archived=true",
        headers=headers,
    )
    assert archived_warehouses.status_code == 200
    assert archived_warehouses.json()[0]["is_active"] is False

    audit_logs = client.get("/api/v1/audit-logs", headers=headers)
    actions = {entry["action"] for entry in audit_logs.json()}
    assert {
        "inventory.warehouse_created",
        "inventory.warehouse_updated",
        "inventory.warehouse_deleted",
        "inventory.stock_movement_recorded",
    }.issubset(actions)
