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
        f"sqlite:///{tmp_path / 'catalog_customers_api.db'}",
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
            "company_name": "ChoiceOye Test Company",
            "username": "admin",
            "password": "admin12345",
            "full_name": "Admin User",
            "email": "catalog-admin@example.com",
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert "catalog.manage" in payload["permissions"]
    assert "customers.manage" in payload["permissions"]
    return str(payload["access_token"])


def create_second_tenant_token(harness: ApiHarness) -> str:
    with harness.session_factory() as db:
        company_id = new_uuid()
        user_id = new_uuid()
        role_id = new_uuid()
        company = Company(id=company_id, name="Second Company", status="active")
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
        return issued.token


def test_catalog_crud_validation_auth_and_tenant_isolation(harness: ApiHarness) -> None:
    client = harness.client
    assert client.get("/api/v1/catalog/products").status_code == 401

    token = complete_first_use_setup(client)
    headers = bearer(token)

    invalid_category = client.post(
        "/api/v1/catalog/categories",
        headers=headers,
        json={"name": "x"},
    )
    assert invalid_category.status_code == 422

    category = client.post(
        "/api/v1/catalog/categories",
        headers=headers,
        json={"name": "Mobile Phones", "slug": "mobile-phones"},
    )
    assert category.status_code == 201
    category_id = category.json()["id"]

    duplicate_category = client.post(
        "/api/v1/catalog/categories",
        headers=headers,
        json={"name": "Duplicate Mobile", "slug": "mobile-phones"},
    )
    assert duplicate_category.status_code == 409

    brand = client.post(
        "/api/v1/catalog/brands",
        headers=headers,
        json={"name": "Choice Brand"},
    )
    assert brand.status_code == 201
    brand_id = brand.json()["id"]

    missing_category_product = client.post(
        "/api/v1/catalog/products",
        headers=headers,
        json={"name": "Bad Product", "category_id": "missing"},
    )
    assert missing_category_product.status_code == 404

    product = client.post(
        "/api/v1/catalog/products",
        headers=headers,
        json={
            "name": "iPhone Case",
            "slug": "iphone-case",
            "sku": "CASE-BASE",
            "product_type": "variable",
            "category_id": category_id,
            "brand_id": brand_id,
            "metadata": {"warranty_days": 7},
            "variants": [
                {
                    "name": "Black",
                    "sku": "CASE-BLK",
                    "price_minor": 150000,
                    "currency": "PKR",
                    "attributes": {"color": "black"},
                }
            ],
            "images": [{"url": "https://example.test/case.jpg", "alt_text": "Case"}],
        },
    )
    assert product.status_code == 201
    product_payload = product.json()
    product_id = product_payload["id"]
    assert product_payload["variants"][0]["sku"] == "CASE-BLK"
    assert product_payload["images"][0]["alt_text"] == "Case"

    code_suggestion = client.get("/api/v1/catalog/products/code-suggestion", headers=headers)
    assert code_suggestion.status_code == 200
    code_suggestion_payload = code_suggestion.json()
    assert code_suggestion_payload["sku"].startswith("CO-")
    assert code_suggestion_payload["barcode"].startswith("20")
    assert len(code_suggestion_payload["barcode"]) == 13

    auto_product = client.post(
        "/api/v1/catalog/products",
        headers=headers,
        json={
            "name": "Auto Product",
            "slug": "auto-product",
            "category_id": category_id,
            "brand_id": brand_id,
        },
    )
    assert auto_product.status_code == 201
    auto_payload = auto_product.json()
    assert auto_payload["sku"].startswith("CO-")
    assert auto_payload["barcode"].isdigit()
    assert len(auto_payload["barcode"]) == 13

    auto_delete = client.delete(f"/api/v1/catalog/products/{auto_payload['id']}", headers=headers)
    assert auto_delete.status_code == 200

    duplicate_product = client.post(
        "/api/v1/catalog/products",
        headers=headers,
        json={"name": "Duplicate Product", "slug": "iphone-case"},
    )
    assert duplicate_product.status_code == 409

    product_update = client.patch(
        f"/api/v1/catalog/products/{product_id}",
        headers=headers,
        json={"status": "draft", "seo_title": "iPhone Case"},
    )
    assert product_update.status_code == 200
    assert product_update.json()["status"] == "draft"

    tenant_two_token = create_second_tenant_token(harness)
    tenant_two_headers = bearer(tenant_two_token)
    assert client.get(
        f"/api/v1/catalog/products/{product_id}",
        headers=tenant_two_headers,
    ).status_code == 404
    assert client.get("/api/v1/catalog/products", headers=tenant_two_headers).json() == []

    delete_product = client.delete(f"/api/v1/catalog/products/{product_id}", headers=headers)
    assert delete_product.status_code == 200
    assert delete_product.json() == {"ok": True}

    active_products = client.get("/api/v1/catalog/products", headers=headers)
    assert active_products.status_code == 200
    assert active_products.json() == []

    archived_products = client.get(
        "/api/v1/catalog/products?include_archived=true",
        headers=headers,
    )
    assert archived_products.status_code == 200
    assert archived_products.json()[0]["status"] == "archived"

    permanent_delete = client.delete(
        f"/api/v1/catalog/products/{product_id}/permanent",
        headers=headers,
    )
    assert permanent_delete.status_code == 200
    assert permanent_delete.json() == {"ok": True}
    assert client.get(f"/api/v1/catalog/products/{product_id}", headers=headers).status_code == 404
    archived_after_permanent_delete = client.get(
        "/api/v1/catalog/products?include_archived=true",
        headers=headers,
    )
    assert product_id not in {row["id"] for row in archived_after_permanent_delete.json()}

    audit_logs = client.get("/api/v1/audit-logs", headers=headers)
    actions = {entry["action"] for entry in audit_logs.json()}
    assert {
        "catalog.category_created",
        "catalog.brand_created",
        "catalog.product_created",
        "catalog.product_updated",
        "catalog.product_deleted",
        "catalog.product_permanently_deleted",
    }.issubset(actions)


def test_product_permanent_delete_refuses_stock_history(harness: ApiHarness) -> None:
    client = harness.client
    token = complete_first_use_setup(client)
    headers = bearer(token)

    product = client.post(
        "/api/v1/catalog/products",
        headers=headers,
        json={"name": "Stock History Product", "slug": "stock-history-product"},
    )
    assert product.status_code == 201
    product_id = product.json()["id"]
    warehouse = client.post(
        "/api/v1/inventory/warehouses",
        headers=headers,
        json={"code": "MAIN", "name": "Main Warehouse"},
    )
    assert warehouse.status_code == 201
    stock = client.post(
        "/api/v1/inventory/stock-movements",
        headers=headers,
        json={
            "warehouse_id": warehouse.json()["id"],
            "product_id": product_id,
            "movement_type": "adjustment",
            "quantity_delta": 1,
            "reason": "Permanent delete protection",
        },
    )
    assert stock.status_code == 201

    assert (
        client.delete(f"/api/v1/catalog/products/{product_id}", headers=headers).status_code
        == 200
    )
    permanent_delete = client.delete(
        f"/api/v1/catalog/products/{product_id}/permanent",
        headers=headers,
    )
    assert permanent_delete.status_code == 409
    assert "stock history" in permanent_delete.text


def test_customer_crud_validation_auth_and_tenant_isolation(harness: ApiHarness) -> None:
    client = harness.client
    assert client.get("/api/v1/customers").status_code == 401

    token = complete_first_use_setup(client)
    headers = bearer(token)

    invalid_customer = client.post(
        "/api/v1/customers",
        headers=headers,
        json={"full_name": "x"},
    )
    assert invalid_customer.status_code == 422

    customer = client.post(
        "/api/v1/customers",
        headers=headers,
        json={
            "full_name": "Sara Customer",
            "email": "sara@example.com",
            "phone": "+923001234567",
            "tags": ["VIP", "Retail"],
            "opening_note": "Prefers WhatsApp updates.",
            "addresses": [
                {
                    "label": "home",
                    "line1": "House 1",
                    "city": "Lahore",
                    "country": "PK",
                    "is_default": True,
                }
            ],
        },
    )
    assert customer.status_code == 201
    customer_payload = customer.json()
    customer_id = customer_payload["id"]
    assert customer_payload["addresses"][0]["city"] == "Lahore"
    assert customer_payload["tags"] == ["retail", "vip"]
    assert customer_payload["notes"][0]["note"] == "Prefers WhatsApp updates."

    duplicate_customer = client.post(
        "/api/v1/customers",
        headers=headers,
        json={"full_name": "Duplicate", "email": "sara@example.com"},
    )
    assert duplicate_customer.status_code == 409

    address = client.post(
        f"/api/v1/customers/{customer_id}/addresses",
        headers=headers,
        json={"line1": "Office 1", "city": "Karachi", "country": "PK"},
    )
    assert address.status_code == 201
    assert address.json()["city"] == "Karachi"

    note = client.post(
        f"/api/v1/customers/{customer_id}/notes",
        headers=headers,
        json={"note": "Asked about wholesale pricing."},
    )
    assert note.status_code == 201

    update_customer = client.patch(
        f"/api/v1/customers/{customer_id}",
        headers=headers,
        json={"phone": "+923009999999", "tags": ["Wholesale"]},
    )
    assert update_customer.status_code == 200
    assert update_customer.json()["phone"] == "+923009999999"
    assert update_customer.json()["tags"] == ["wholesale"]

    tenant_two_token = create_second_tenant_token(harness)
    tenant_two_headers = bearer(tenant_two_token)
    tenant_two_detail = client.get(
        f"/api/v1/customers/{customer_id}",
        headers=tenant_two_headers,
    )
    assert tenant_two_detail.status_code == 404
    assert client.get("/api/v1/customers", headers=tenant_two_headers).json() == []

    tenant_two_customer = client.post(
        "/api/v1/customers",
        headers=tenant_two_headers,
        json={"full_name": "Sara Customer", "email": "sara@example.com"},
    )
    assert tenant_two_customer.status_code == 201

    delete_customer = client.delete(f"/api/v1/customers/{customer_id}", headers=headers)
    assert delete_customer.status_code == 200
    assert client.get("/api/v1/customers", headers=headers).json() == []

    archived_customers = client.get(
        "/api/v1/customers?include_archived=true",
        headers=headers,
    )
    assert archived_customers.status_code == 200
    assert archived_customers.json()[0]["status"] == "archived"

    audit_logs = client.get("/api/v1/audit-logs", headers=headers)
    actions = {entry["action"] for entry in audit_logs.json()}
    assert {
        "customers.customer_created",
        "customers.customer_updated",
        "customers.customer_deleted",
        "customers.address_created",
        "customers.note_created",
    }.issubset(actions)


def test_product_editor_fields_variants_images_and_uploads(
    harness: ApiHarness,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from erp.packages.core.api import routes

    client = harness.client
    token = complete_first_use_setup(client)
    headers = bearer(token)

    category = client.post("/api/v1/catalog/categories", headers=headers, json={"name": "Cases"})
    assert category.status_code == 201
    category_id = category.json()["id"]

    create_resp = client.post(
        "/api/v1/catalog/products",
        headers=headers,
        json={
            "name": "Editor Product",
            "sku": "EDITOR-1",
            "product_type": "simple",
            "status": "draft",
            "category_id": category_id,
            "category_ids": [category_id],
            "description": "Long description",
            "short_description": "Short description",
            "visibility": "search",
            "featured": True,
            "global_unique_id": "GTIN-1",
            "regular_price_minor": 12345,
            "sale_price_minor": 9999,
            "tax_status": "taxable",
            "tax_class": "standard",
            "manage_stock": True,
            "stock_quantity": 5,
            "stock_status": "instock",
            "backorders": "notify",
            "sold_individually": True,
            "weight": "1.2",
            "length": "10",
            "width": "5",
            "height": "2",
            "shipping_class": "small",
            "reviews_allowed": False,
            "purchase_note": "Thanks",
            "menu_order": 7,
            "tags": ["featured", "mobile"],
            "attributes": [{"name": "Color", "options": ["Black"]}],
            "default_attributes": [{"name": "Color", "option": "Black"}],
            "custom_metadata": {"erp": "yes"},
            "metadata": {"warranty_days": 7},
            "variants": [
                {
                    "name": "Black",
                    "sku": "EDITOR-1-BLK",
                    "price_minor": 12345,
                    "sale_price_minor": 9999,
                    "manage_stock": True,
                    "stock_quantity": 5,
                    "stock_status": "instock",
                    "backorders": "no",
                    "weight": "1.1",
                    "length": "9",
                    "width": "4",
                    "height": "1",
                    "shipping_class": "small",
                    "description": "Variant description",
                    "image_url": "https://example.test/variant.jpg",
                    "metadata": {"color": "black"},
                }
            ],
            "images": [
                {
                    "url": "https://example.test/product.jpg",
                    "alt_text": "Product",
                    "sort_order": 0,
                    "external_id": "200",
                    "name": "product.jpg",
                }
            ],
        },
    )
    assert create_resp.status_code == 201
    payload = create_resp.json()
    product_id = payload["id"]
    assert payload["regular_price_minor"] == 12345
    assert payload["short_description"] == "Short description"
    assert payload["tags"] == ["featured", "mobile"]
    assert payload["variants"][0]["sale_price_minor"] == 9999
    assert payload["images"][0]["external_id"] == "200"

    update_resp = client.patch(
        f"/api/v1/catalog/products/{product_id}",
        headers=headers,
        json={
            "regular_price_minor": 15000,
            "tags": ["updated"],
            "variants": [{"name": "Default", "sku": "EDITOR-1-NEW", "price_minor": 15000}],
            "images": [
                {
                    "url": "https://example.test/updated.jpg",
                    "alt_text": "Updated",
                    "sort_order": 0,
                }
            ],
        },
    )
    assert update_resp.status_code == 200
    updated = update_resp.json()
    assert updated["regular_price_minor"] == 15000
    assert updated["tags"] == ["updated"]
    assert len(updated["variants"]) == 1
    assert updated["variants"][0]["sku"] == "EDITOR-1-NEW"
    assert len(updated["images"]) == 1
    assert updated["images"][0]["url"] == "https://example.test/updated.jpg"

    upload_resp = client.post(
        f"/api/v1/catalog/products/{product_id}/images/upload",
        headers=headers,
        files={"file": ("image.png", b"\x89PNG\r\n\x1a\nsmall", "image/png")},
    )
    assert upload_resp.status_code == 201
    assert upload_resp.json()["url"].startswith("/media/products/")

    bad_extension = client.post(
        f"/api/v1/catalog/products/{product_id}/images/upload",
        headers=headers,
        files={"file": ("image.txt", b"bad", "text/plain")},
    )
    assert bad_extension.status_code == 422

    monkeypatch.setattr(routes, "PRODUCT_IMAGE_MAX_BYTES", 4)
    too_large = client.post(
        f"/api/v1/catalog/products/{product_id}/images/upload",
        headers=headers,
        files={"file": ("image.png", b"12345", "image/png")},
    )
    assert too_large.status_code == 413

    tenant_two_token = create_second_tenant_token(harness)
    tenant_upload = client.post(
        f"/api/v1/catalog/products/{product_id}/images/upload",
        headers=bearer(tenant_two_token),
        files={"file": ("image.png", b"\x89PNG\r\n\x1a\nsmall", "image/png")},
    )
    assert tenant_upload.status_code == 404
