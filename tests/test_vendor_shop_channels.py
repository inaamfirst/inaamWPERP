from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from erp.apps.api.main import create_app
from erp.packages.core.db.base import Base
from erp.packages.core.db.models import Company, Customer, Order, OrderItem, Product, User, Vendor, VendorOrderItem
from erp.packages.core.db.session import get_session
from erp.packages.core.inventory_services import current_stock, record_stock_movement
from erp.packages.core.schemas import StockMovementCreate
from erp.packages.core.shop_services import vendor_shop_warehouse
from erp.packages.core.woocommerce_services import (
    deduct_woocommerce_order_stock,
    restore_cancelled_woocommerce_order_stock,
)


@pytest.fixture()
def client(tmp_path: Path) -> Iterator[TestClient]:
    engine = create_engine(
        f"sqlite:///{tmp_path / 'vendor_shop_channels.db'}",
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
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
    engine.dispose()


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_vendor_pos_history_is_separate_from_online_orders_and_uses_shop_stock(
    client: TestClient,
) -> None:
    admin = client.post(
        "/api/v1/setup/first-use",
        json={
            "company_name": "Channel Test Company",
            "workspace_slug": "channel-test",
            "username": "admin",
            "password": "admin12345",
            "email": "admin@example.com",
        },
    ).json()
    admin_headers = _headers(str(admin["access_token"]))
    registration = client.post(
        "/api/v1/auth/register/vendor",
        json={
            "workspace_slug": "channel-test",
            "business_name": "Channel Vendor",
            "username": "channel_vendor",
            "password": "vendor12345",
            "email": "vendor@example.com",
        },
    )
    assert registration.status_code == 201, registration.text
    vendor_id = registration.json()["vendor_id"]
    assert client.post(
        f"/api/v1/marketplace/vendors/{vendor_id}/approve", headers=admin_headers
    ).status_code == 200
    login = client.post(
        "/api/v1/auth/login",
        json={
            "workspace_slug": "channel-test",
            "username": "channel_vendor",
            "password": "vendor12345",
        },
    )
    assert login.status_code == 200, login.text
    vendor_headers = _headers(str(login.json()["access_token"]))

    product = client.post(
        "/api/v1/vendor/catalog/products",
        headers=vendor_headers,
        json={
            "name": "Shared Stock Product",
            "regular_price_minor": 2500,
            "manage_stock": True,
            "stock_quantity": 5,
        },
    )
    assert product.status_code == 201, product.text
    product_id = product.json()["id"]
    catalog = client.get("/api/v1/commerce/vendor/shop/catalog", headers=vendor_headers)
    assert catalog.status_code == 200, catalog.text
    assert catalog.json()[0]["stock_quantity"] == 5

    sale = client.post(
        "/api/v1/commerce/vendor/pos/sales",
        headers=vendor_headers,
        json={
            "customer_name": "Walk-in customer",
            "items": [{"product_id": product_id, "quantity": 2}],
            "payments": [{"amount_minor": 5000, "currency": "PKR", "method": "cash"}],
            "idempotency_key": "vendor-pos-history-1",
        },
    )
    assert sale.status_code == 201, sale.text
    assert sale.json()["sales_channel"] == "pos"

    history = client.get("/api/v1/commerce/vendor/shop/sales", headers=vendor_headers)
    assert history.status_code == 200, history.text
    assert len(history.json()) == 1
    assert history.json()[0]["bill_number"] == sale.json()["order_number"]
    assert history.json()[0]["item_quantity"] == 2
    assert history.json()[0]["items"][0]["name"] == "Shared Stock Product"

    online_orders = client.get("/api/v1/marketplace/vendor/orders", headers=vendor_headers)
    assert online_orders.status_code == 200, online_orders.text
    assert online_orders.json() == []

    refreshed_catalog = client.get("/api/v1/commerce/vendor/shop/catalog", headers=vendor_headers)
    assert refreshed_catalog.status_code == 200
    assert refreshed_catalog.json()[0]["stock_quantity"] == 3
    accounting = client.get("/api/v1/commerce/vendor/shop/accounting", headers=vendor_headers)
    assert accounting.status_code == 200, accounting.text
    assert accounting.json()["shop"]["sales_minor"] == 5000
    assert accounting.json()["online"]["sales_minor"] == 0


def test_woocommerce_sale_deducts_and_cancel_restores_the_same_vendor_shop_stock(
    tmp_path: Path,
) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'woocommerce_shared_stock.db'}", future=True)
    Base.metadata.create_all(engine)
    try:
        with Session(engine) as db:
            company = Company(name="Online Stock Company", slug="online-stock-company")
            db.add(company)
            db.flush()
            user = User(company_id=company.id, username="sync-user", password_hash="hash")
            vendor = Vendor(company_id=company.id, name="Online Vendor", slug="online-vendor", status="approved")
            customer = Customer(company_id=company.id, full_name="Online Customer")
            db.add_all([user, vendor, customer])
            db.flush()
            product = Product(
                company_id=company.id,
                vendor_id=vendor.id,
                name="Shared Online Product",
                slug="shared-online-product",
                regular_price_minor=1000,
                manage_stock=True,
            )
            db.add(product)
            db.flush()
            warehouse = vendor_shop_warehouse(db, company.id, vendor.id)
            record_stock_movement(
                db,
                company_id=company.id,
                user_id=user.id,
                payload=StockMovementCreate(
                    movement_type="opening",
                    warehouse_id=warehouse.id,
                    product_id=product.id,
                    quantity=5,
                    reference_type="test",
                    reference_id="opening",
                ),
            )
            order = Order(
                company_id=company.id,
                customer_id=customer.id,
                order_number="WC-1001",
                sales_channel="woocommerce",
                order_source="woocommerce",
                external_order_id="1001",
                status="confirmed",
            )
            db.add(order)
            db.flush()
            item = OrderItem(
                company_id=company.id,
                order_id=order.id,
                product_id=product.id,
                vendor_id=vendor.id,
                name=product.name,
                quantity=2,
                unit_price_minor=1000,
                line_total_minor=2000,
            )
            db.add(item)
            db.flush()
            db.add(VendorOrderItem(
                company_id=company.id,
                vendor_id=vendor.id,
                order_id=order.id,
                order_item_id=item.id,
                product_id=product.id,
                name=product.name,
                quantity=2,
                unit_price_minor=1000,
                line_total_minor=2000,
            ))
            db.flush()

            assert deduct_woocommerce_order_stock(db, company_id=company.id, order=order)
            assert order.reservation_status == "deducted"
            assert current_stock(db, company_id=company.id, warehouse_id=warehouse.id, product_id=product.id, variant_id=None) == 3
            # Repeated webhook/poll processing cannot deduct the same order twice.
            assert deduct_woocommerce_order_stock(db, company_id=company.id, order=order)
            assert current_stock(db, company_id=company.id, warehouse_id=warehouse.id, product_id=product.id, variant_id=None) == 3

            order.status = "cancelled"
            assert restore_cancelled_woocommerce_order_stock(db, company_id=company.id, order=order)
            assert order.reservation_status == "restored"
            assert current_stock(db, company_id=company.id, warehouse_id=warehouse.id, product_id=product.id, variant_id=None) == 5
            assert not restore_cancelled_woocommerce_order_stock(db, company_id=company.id, order=order)
    finally:
        engine.dispose()
