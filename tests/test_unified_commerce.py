from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from erp.apps.api.main import create_app
from erp.packages.core.db.base import Base
from erp.packages.core.db.session import get_session


@pytest.fixture()
def commerce_client(tmp_path: Path) -> Iterator[TestClient]:
    engine = create_engine(
        f"sqlite:///{tmp_path / 'unified_commerce.db'}",
        connect_args={"check_same_thread": False},
        future=True,
    )
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)

    def override_session() -> Iterator[Session]:
        session = sessions()
        try:
            yield session
        finally:
            session.close()

    app = create_app()
    app.dependency_overrides[get_session] = override_session
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.clear()
    engine.dispose()


def auth_headers(client: TestClient) -> dict[str, str]:
    response = client.post(
        "/api/v1/setup/first-use",
        json={
            "company_name": "Unified Commerce Company",
            "username": "admin",
            "password": "admin12345",
            "email": "commerce-admin@example.com",
        },
    )
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def test_admin_pos_channel_listing_reservation_and_support(commerce_client: TestClient) -> None:
    headers = auth_headers(commerce_client)
    warehouse = commerce_client.post(
        "/api/v1/inventory/warehouses",
        headers=headers,
        json={"code": "MAIN", "name": "Main Shop"},
    )
    assert warehouse.status_code == 201, warehouse.text
    warehouse_id = warehouse.json()["id"]

    product = commerce_client.post(
        "/api/v1/catalog/products",
        headers=headers,
        json={
            "name": "Unified Mug",
            "slug": "unified-mug",
            "sku": "MUG-001",
            "regular_price_minor": 1500,
            "manage_stock": True,
        },
    )
    assert product.status_code == 201, product.text
    product_id = product.json()["id"]
    movement = commerce_client.post(
        "/api/v1/inventory/stock-movements",
        headers=headers,
        json={
            "movement_type": "stock_in",
            "warehouse_id": warehouse_id,
            "product_id": product_id,
            "quantity": 5,
        },
    )
    assert movement.status_code == 201, movement.text

    listing = commerce_client.put(
        f"/api/v1/commerce/admin/products/{product_id}/channel",
        headers=headers,
        json={"channel": "woocommerce", "listing_status": "published"},
    )
    assert listing.status_code == 200, listing.text
    assert listing.json()["listing_status"] == "published"

    sale = commerce_client.post(
        "/api/v1/commerce/admin/pos/sales",
        headers=headers,
        json={
            "warehouse_id": warehouse_id,
            "customer_name": "Shop Customer",
            "items": [{"product_id": product_id, "quantity": 2}],
            "payments": [{"amount_minor": 3000, "currency": "PKR", "method": "cash"}],
            "idempotency_key": "pos-test-001",
        },
    )
    assert sale.status_code == 201, sale.text
    assert sale.json()["sales_channel"] == "pos"
    assert sale.json()["order_source"] == "pos"

    summary = commerce_client.get("/api/v1/commerce/dashboard?workspace=shop", headers=headers)
    assert summary.status_code == 200, summary.text
    assert summary.json()["order_count"] == 1
    assert summary.json()["shop_sales_minor"] == 3000

    reservation = commerce_client.post(
        "/api/v1/commerce/stock/reservations",
        headers=headers,
        json={
            "warehouse_id": warehouse_id,
            "product_id": product_id,
            "quantity": 2,
            "source_type": "woocommerce",
            "source_id": "wc-1001",
            "idempotency_key": "reservation-test-001",
        },
    )
    assert reservation.status_code == 201, reservation.text
    assert reservation.json()["status"] == "reserved"
    repeated = commerce_client.post(
        "/api/v1/commerce/stock/reservations",
        headers=headers,
        json={
            "warehouse_id": warehouse_id,
            "product_id": product_id,
            "quantity": 2,
            "source_type": "woocommerce",
            "source_id": "wc-1001",
            "idempotency_key": "reservation-test-001",
        },
    )
    assert repeated.status_code == 201
    assert repeated.json()["id"] == reservation.json()["id"]

    contact = commerce_client.post(
        "/api/v1/commerce/admin/support/contacts",
        headers=headers,
        json={"label": "Owner", "role": "owner", "phone": "+92 300 1234567"},
    )
    assert contact.status_code == 201, contact.text
    assert contact.json()["whatsapp_url"].startswith("https://wa.me/923001234567")
