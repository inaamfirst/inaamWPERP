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
    Customer,
    Order,
    Payment,
    Product,
    User,
    Vendor,
    VendorInventoryMovement,
    VendorProduct,
    VendorSettlement,
    Warehouse,
)
from erp.packages.core.db.session import get_session
from erp.packages.core.security import hash_password


@dataclass(frozen=True)
class Harness:
    client: TestClient
    session_factory: sessionmaker


@pytest.fixture()
def harness(tmp_path: Path) -> Iterator[Harness]:
    engine = create_engine(
        f"sqlite:///{tmp_path / 'auth_vendor_ledger.db'}",
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
    with TestClient(app) as client:
        yield Harness(client=client, session_factory=session_factory)
    app.dependency_overrides.clear()
    engine.dispose()


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def setup(harness: Harness) -> dict[str, object]:
    response = harness.client.post(
        "/api/v1/setup/first-use",
        json={
            "company_name": "Ledger Test Company",
            "workspace_slug": "ledger-test",
            "username": "admin",
            "password": "admin12345",
            "email": "ledger-admin@example.com",
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_refresh_rotation_reuse_detection_and_session_information(harness: Harness) -> None:
    initial = setup(harness)
    access = str(initial["access_token"])
    refresh = str(initial["refresh_token"])

    me = harness.client.get("/api/v1/auth/me", headers=bearer(access))
    assert me.status_code == 200
    assert me.json()["session_id"] == initial["session_id"]
    assert me.json()["session_expires_at"]
    assert me.json()["user"]["account_status"] == "active"

    rotated = harness.client.post("/api/v1/auth/refresh", json={"refresh_token": refresh})
    assert rotated.status_code == 200
    rotated_payload = rotated.json()
    assert rotated_payload["refresh_token"] != refresh

    reuse = harness.client.post("/api/v1/auth/refresh", json={"refresh_token": refresh})
    assert reuse.status_code == 401
    revoked_me = harness.client.get(
        "/api/v1/auth/me", headers=bearer(str(rotated_payload["access_token"]))
    )
    assert revoked_me.status_code == 401


def test_repeated_login_failures_are_rate_limited(harness: Harness) -> None:
    setup(harness)
    payload = {
        "workspace_slug": "ledger-test",
        "username": "admin",
        "password": "incorrect-password",
    }
    for _ in range(5):
        assert harness.client.post("/api/v1/auth/login", json=payload).status_code == 401
    blocked = harness.client.post("/api/v1/auth/login", json=payload)
    assert blocked.status_code == 429


def test_login_throttle_isolated_by_device_and_account(harness: Harness) -> None:
    setup(harness)
    with harness.session_factory() as db:
        admin = db.scalar(select(User).where(User.username == "admin"))
        assert admin is not None
        db.add(
            User(
                company_id=admin.company_id,
                username="second-user",
                email="second-user@example.test",
                password_hash=hash_password("second12345"),
            )
        )
        db.commit()

    device_a = "11111111-1111-4111-8111-111111111111"
    device_b = "22222222-2222-4222-8222-222222222222"
    bad_admin = {
        "workspace_slug": "ledger-test",
        "username": "admin",
        "password": "incorrect-password",
        "login_device_id": device_a,
    }
    for _ in range(5):
        assert harness.client.post("/api/v1/auth/login", json=bad_admin).status_code == 401
    assert harness.client.post("/api/v1/auth/login", json=bad_admin).status_code == 429

    other_device = {**bad_admin, "password": "admin12345", "login_device_id": device_b}
    assert harness.client.post("/api/v1/auth/login", json=other_device).status_code == 200

    other_account = {
        **bad_admin,
        "username": "second-user",
        "password": "second12345",
    }
    assert harness.client.post("/api/v1/auth/login", json=other_account).status_code == 200


def test_final_active_administrator_cannot_be_disabled(harness: Harness) -> None:
    admin = setup(harness)
    token = str(admin["access_token"])
    response = harness.client.patch(
        f"/api/v1/identity/users/{admin['user']['id']}",
        headers=bearer(token),
        json={"account_status": "paused"},
    )
    assert response.status_code == 409
    assert harness.client.get("/api/v1/auth/me", headers=bearer(token)).status_code == 200


def test_public_vendor_registration_approval_pause_and_tenant_isolation(
    harness: Harness,
) -> None:
    admin = setup(harness)
    admin_headers = bearer(str(admin["access_token"]))
    registration = harness.client.post(
        "/api/v1/auth/register/vendor",
        json={
            "workspace_slug": "ledger-test",
            "business_name": "Pending Vendor",
            "username": "pending_vendor",
            "email": "pending-vendor@example.com",
            "password": "vendor12345",
            "contact_name": "Vendor Owner",
        },
    )
    assert registration.status_code == 201
    registration_payload = registration.json()
    assert registration_payload["account_status"] == "pending"
    assert registration_payload["vendor_status"] == "pending"

    pending_login = harness.client.post(
        "/api/v1/auth/login",
        json={
            "workspace_slug": "ledger-test",
            "username": "pending_vendor",
            "password": "vendor12345",
        },
    )
    assert pending_login.status_code == 403

    approved = harness.client.post(
        f"/api/v1/marketplace/vendors/{registration_payload['vendor_id']}/approve",
        headers=admin_headers,
    )
    assert approved.status_code == 200
    assert approved.json()["status"] == "active"

    active_login = harness.client.post(
        "/api/v1/auth/login",
        json={
            "workspace_slug": "ledger-test",
            "username": "pending_vendor",
            "password": "vendor12345",
        },
    )
    assert active_login.status_code == 200
    vendor_token = str(active_login.json()["access_token"])
    assert {
        "vendor.profile.view",
        "vendor.products.view",
        "vendor.orders.view",
        "vendor.settlements.view",
    } <= set(active_login.json()["permissions"])
    assert "vendor.ledger.view" in active_login.json()["permissions"]
    assert "ledger.view" not in active_login.json()["permissions"]

    own_overview = harness.client.get("/api/v1/vendor/me", headers=bearer(vendor_token))
    assert own_overview.status_code == 200
    assert (
        harness.client.get(
            "/api/v1/vendor/ledger/overview", headers=bearer(vendor_token)
        ).status_code
        == 200
    )
    assert (
        harness.client.get("/api/v1/vendor/orders", headers=bearer(vendor_token)).status_code == 200
    )
    assert (
        harness.client.get("/api/v1/vendor/settlements", headers=bearer(vendor_token)).status_code
        == 200
    )
    invalid_range = harness.client.get(
        "/api/v1/vendor/orders",
        headers=bearer(vendor_token),
        params={"date_from": "2026-02-01T00:00:00Z", "date_to": "2026-01-01T00:00:00Z"},
    )
    assert invalid_range.status_code == 422
    assert (
        harness.client.get(
            "/api/v1/vendor/orders", headers=bearer(vendor_token), params={"limit": 501}
        ).status_code
        == 422
    )
    audit = harness.client.get(
        f"/api/v1/ledger/vendors/{registration_payload['vendor_id']}/audit",
        headers=admin_headers,
    )
    assert audit.status_code == 200
    payables = harness.client.get("/api/v1/ledger/reports/vendor-payables", headers=admin_headers)
    assert payables.status_code == 200
    vendor_payable = next(
        row for row in payables.json() if row["vendor_id"] == registration_payload["vendor_id"]
    )
    assert {
        "current_minor",
        "days_31_60_minor",
        "days_61_90_minor",
        "days_over_90_minor",
        "outstanding_minor",
    } <= vendor_payable.keys()
    assert (
        harness.client.get(
            "/api/v1/ledger/vendors/not-in-this-company/overview",
            headers=admin_headers,
        ).status_code
        == 404
    )
    forbidden_company_ledger = harness.client.get(
        "/api/v1/ledger/overview", headers=bearer(vendor_token)
    )
    assert forbidden_company_ledger.status_code == 403

    paused = harness.client.patch(
        f"/api/v1/marketplace/vendors/{registration_payload['vendor_id']}/status",
        headers=admin_headers,
        json={"status": "paused", "reason": "Compliance review"},
    )
    assert paused.status_code == 200
    assert paused.json()["status"] == "paused"
    assert harness.client.get("/api/v1/vendor/me", headers=bearer(vendor_token)).status_code == 401


def test_public_staff_registration_queue_approval_and_duplicate_conflict(
    harness: Harness,
) -> None:
    admin = setup(harness)
    admin_headers = bearer(str(admin["access_token"]))
    payload = {
        "workspace_slug": "ledger-test",
        "username": "pending_staff",
        "email": "pending-staff@example.com",
        "password": "staff12345",
        "full_name": "Pending Staff",
    }
    registration = harness.client.post("/api/v1/auth/register/user", json=payload)
    assert registration.status_code == 201, registration.text
    assert registration.json()["account_status"] == "pending"

    forbidden_roles = harness.client.post(
        "/api/v1/auth/register/user",
        json={**payload, "username": "public_role_attempt", "role_ids": ["administrator"]},
    )
    assert forbidden_roles.status_code == 422

    duplicate = harness.client.post("/api/v1/auth/register/user", json=payload)
    assert duplicate.status_code == 409
    assert duplicate.json()["detail"] == "The supplied login details are already in use."

    pending_login = harness.client.post(
        "/api/v1/auth/login",
        json={
            "workspace_slug": "ledger-test",
            "username": "pending_staff",
            "password": "staff12345",
        },
    )
    assert pending_login.status_code == 403

    pending = harness.client.get(
        "/api/v1/identity/registrations/pending", headers=admin_headers
    )
    assert pending.status_code == 200
    pending_row = next(row for row in pending.json() if row["username"] == "pending_staff")
    assert pending_row["registration_type"] == "staff"
    assert pending_row["role_ids"] == []

    roles = harness.client.get("/api/v1/identity/roles", headers=admin_headers)
    assert roles.status_code == 200
    selected_role = next(role for role in roles.json() if role["name"] != "Administrator")
    approved = harness.client.post(
        f"/api/v1/identity/registrations/{pending_row['id']}/approve",
        headers=admin_headers,
        json={"role_ids": [selected_role["id"]]},
    )
    assert approved.status_code == 200, approved.text
    assert approved.json()["account_status"] == "active"
    assert approved.json()["role_ids"] == [selected_role["id"]]

    active_login = harness.client.post(
        "/api/v1/auth/login",
        json={
            "workspace_slug": "ledger-test",
            "username": "pending_staff",
            "password": "staff12345",
        },
    )
    assert active_login.status_code == 200


def test_registration_queue_reject_stops_vendor_and_user(harness: Harness) -> None:
    admin = setup(harness)
    admin_headers = bearer(str(admin["access_token"]))
    registration = harness.client.post(
        "/api/v1/auth/register/vendor",
        json={
            "workspace_slug": "ledger-test",
            "business_name": "Rejected Vendor",
            "username": "rejected_vendor",
            "email": "rejected-vendor@example.com",
            "password": "vendor12345",
        },
    )
    assert registration.status_code == 201
    pending = harness.client.get(
        "/api/v1/identity/registrations/pending", headers=admin_headers
    )
    row = next(item for item in pending.json() if item["username"] == "rejected_vendor")
    rejected = harness.client.post(
        f"/api/v1/identity/registrations/{row['id']}/reject",
        headers=admin_headers,
        json={"reason": "Not eligible"},
    )
    assert rejected.status_code == 200
    assert rejected.json()["account_status"] == "stopped"
    assert rejected.json()["vendor_profile"]["status"] == "stopped"
    assert harness.client.post(
        "/api/v1/auth/login",
        json={
            "workspace_slug": "ledger-test",
            "username": "rejected_vendor",
            "password": "vendor12345",
        },
    ).status_code == 403


def test_registration_queue_approve_activates_vendor(harness: Harness) -> None:
    admin = setup(harness)
    admin_headers = bearer(str(admin["access_token"]))
    registration = harness.client.post(
        "/api/v1/auth/register/vendor",
        json={
            "workspace_slug": "ledger-test",
            "business_name": "Approved Vendor",
            "username": "approved_vendor",
            "email": "approved-vendor@example.com",
            "password": "vendor12345",
        },
    )
    assert registration.status_code == 201
    pending = harness.client.get(
        "/api/v1/identity/registrations/pending", headers=admin_headers
    )
    row = next(item for item in pending.json() if item["username"] == "approved_vendor")
    approved = harness.client.post(
        f"/api/v1/identity/registrations/{row['id']}/approve",
        headers=admin_headers,
        json={},
    )
    assert approved.status_code == 200, approved.text
    assert approved.json()["account_status"] == "active"
    assert approved.json()["vendor_profile"]["status"] == "active"
    assert approved.json()["role_names"] == ["Vendor"]
    assert harness.client.post(
        "/api/v1/auth/login",
        json={
            "workspace_slug": "ledger-test",
            "username": "approved_vendor",
            "password": "vendor12345",
        },
    ).status_code == 200


def test_admin_created_vendor_is_active_and_temporary_password_must_change(
    harness: Harness,
) -> None:
    admin = setup(harness)
    created = harness.client.post(
        "/api/v1/marketplace/vendors/with-account",
        headers=bearer(str(admin["access_token"])),
        json={
            "business_name": "Admin Vendor",
            "username": "admin_vendor",
            "email": "admin-vendor@example.com",
            "password": "temporary12345",
            "use_activation": False,
        },
    )
    assert created.status_code == 201, created.text
    assert created.json()["vendor"]["status"] == "active"
    assert created.json()["user"]["account_status"] == "active"
    assert created.json()["user"]["must_change_password"] is True
    assert created.json()["activation_token"] is None

    login = harness.client.post(
        "/api/v1/auth/login",
        json={
            "workspace_slug": "ledger-test",
            "username": "admin_vendor",
            "password": "temporary12345",
        },
    )
    assert login.status_code == 200
    token = str(login.json()["access_token"])
    assert (
        harness.client.get("/api/v1/vendor/ledger/overview", headers=bearer(token)).status_code
        == 403
    )
    changed = harness.client.post(
        "/api/v1/auth/change-password",
        headers=bearer(token),
        json={
            "current_password": "temporary12345",
            "new_password": "permanent12345",
        },
    )
    assert changed.status_code == 204
    assert harness.client.get("/api/v1/vendor/me", headers=bearer(token)).status_code == 200
    assert (
        harness.client.get("/api/v1/vendor/ledger/overview", headers=bearer(token)).status_code
        == 200
    )


def test_balanced_immutable_journal_reversal_and_period_lock(harness: Harness) -> None:
    admin = setup(harness)
    headers = bearer(str(admin["access_token"]))
    accounts_response = harness.client.get("/api/v1/ledger/accounts", headers=headers)
    assert accounts_response.status_code == 200
    accounts = {row["code"]: row for row in accounts_response.json()}

    unbalanced = harness.client.post(
        "/api/v1/ledger/journals",
        headers=headers,
        json={
            "source_type": "manual_adjustment",
            "source_id": "unbalanced-1",
            "memo": "Must fail",
            "lines": [
                {"account_id": accounts["1000"]["id"], "debit_minor": 1000},
                {"account_id": accounts["4000"]["id"], "credit_minor": 900},
            ],
        },
    )
    assert unbalanced.status_code == 422

    journal_payload = {
        "source_type": "manual_adjustment",
        "source_id": "manual-1",
        "idempotency_key": "manual-1",
        "memo": "Opening correction",
        "lines": [
            {"account_id": accounts["1000"]["id"], "debit_minor": 1000},
            {"account_id": accounts["4000"]["id"], "credit_minor": 1000},
        ],
    }
    posted = harness.client.post("/api/v1/ledger/journals", headers=headers, json=journal_payload)
    assert posted.status_code == 201, posted.text
    journal = posted.json()
    assert sum(line["debit_minor"] for line in journal["lines"]) == 1000
    assert sum(line["credit_minor"] for line in journal["lines"]) == 1000
    assert (
        harness.client.post(
            "/api/v1/ledger/journals", headers=headers, json=journal_payload
        ).status_code
        == 409
    )

    reversal = harness.client.post(
        f"/api/v1/ledger/journals/{journal['id']}/reverse",
        headers=headers,
        json={"reason": "Correction required"},
    )
    assert reversal.status_code == 200
    assert reversal.json()["reversal_of_id"] == journal["id"]
    assert (
        harness.client.post(
            f"/api/v1/ledger/journals/{journal['id']}/reverse",
            headers=headers,
            json={"reason": "Cannot reverse twice"},
        ).status_code
        == 409
    )

    trial = harness.client.get("/api/v1/ledger/trial-balance", headers=headers)
    assert trial.status_code == 200
    assert all(row["debit_minor"] >= 0 and row["credit_minor"] >= 0 for row in trial.json())
    periods = harness.client.get("/api/v1/ledger/periods", headers=headers).json()
    assert len(periods) == 1
    locked = harness.client.patch(
        f"/api/v1/ledger/periods/{periods[0]['id']}",
        headers=headers,
        json={"status": "locked", "reason": "Month-end close"},
    )
    assert locked.status_code == 200
    locked_post = harness.client.post(
        "/api/v1/ledger/journals",
        headers=headers,
        json={**journal_payload, "source_id": "manual-2", "idempotency_key": "manual-2"},
    )
    assert locked_post.status_code == 409


def test_vendor_inventory_is_append_only_idempotent_and_rebuildable(harness: Harness) -> None:
    admin = setup(harness)
    headers = bearer(str(admin["access_token"]))
    company_id = str(admin["company"]["id"])
    with harness.session_factory() as db:
        vendor = Vendor(
            company_id=company_id,
            name="Stock Vendor",
            slug="stock-vendor",
            status="active",
        )
        product = Product(
            company_id=company_id,
            vendor_id=None,
            name="Stock Product",
            slug="stock-product",
            sku="STOCK-1",
            status="active",
            visibility="visible",
            regular_price_minor=1000,
        )
        warehouse = Warehouse(
            company_id=company_id,
            code="MAIN",
            name="Main Warehouse",
            is_active=True,
        )
        db.add_all([vendor, product, warehouse])
        db.flush()
        assignment = VendorProduct(
            company_id=company_id,
            vendor_id=vendor.id,
            product_id=product.id,
            approval_status="approved",
            ownership_type="company_owned",
        )
        db.add(assignment)
        db.commit()
        vendor_id, product_id, warehouse_id = vendor.id, product.id, warehouse.id

    opening_payload = {
        "vendor_id": vendor_id,
        "product_id": product_id,
        "warehouse_id": warehouse_id,
        "movement_type": "opening_balance",
        "quantity_delta": 10,
        "reserved_quantity_delta": 0,
        "ownership_type": "company_owned",
        "unit_cost_minor": 400,
        "currency": "PKR",
        "source_type": "opening_balance",
        "source_id": "opening-1",
        "idempotency_key": "opening-1",
        "reason": "Administrator-counted opening balance",
    }
    opening = harness.client.post(
        "/api/v1/ledger/vendor-inventory/movements",
        headers=headers,
        json=opening_payload,
    )
    assert opening.status_code == 201, opening.text
    assert opening.json()["quantity_after"] == 10
    assert (
        harness.client.post(
            "/api/v1/ledger/vendor-inventory/movements",
            headers=headers,
            json=opening_payload,
        ).status_code
        == 409
    )

    reservation = harness.client.post(
        "/api/v1/ledger/vendor-inventory/movements",
        headers=headers,
        json={
            **opening_payload,
            "movement_type": "reservation",
            "quantity_delta": 0,
            "reserved_quantity_delta": 3,
            "unit_cost_minor": None,
            "source_type": "order",
            "source_id": "order-1",
            "idempotency_key": "reservation-1",
            "reason": "Reserve for order",
        },
    )
    assert reservation.status_code == 201
    stock = harness.client.get(f"/api/v1/ledger/vendors/{vendor_id}/stock", headers=headers)
    assert stock.status_code == 200
    assert stock.json()[0]["on_hand_quantity"] == 10
    assert stock.json()[0]["reserved_quantity"] == 3
    assert stock.json()[0]["available_quantity"] == 7

    insufficient = harness.client.post(
        "/api/v1/ledger/vendor-inventory/movements",
        headers=headers,
        json={
            **opening_payload,
            "movement_type": "sale",
            "quantity_delta": -20,
            "source_type": "order",
            "source_id": "order-2",
            "idempotency_key": "sale-too-large",
            "reason": "Must reject negative stock",
        },
    )
    assert insufficient.status_code == 409

    reconciliation = harness.client.get("/api/v1/ledger/reconciliation", headers=headers)
    assert reconciliation.status_code == 200
    assert not any(
        row["issue_type"] == "vendor_stock_projection_drift" for row in reconciliation.json()
    )
    with harness.session_factory() as db:
        movements = list(
            db.scalars(
                select(VendorInventoryMovement).where(
                    VendorInventoryMovement.vendor_id == vendor_id
                )
            ).all()
        )
        assert len(movements) == 2


def test_reconciliation_detects_missing_business_postings_and_settlement_mismatch(
    harness: Harness,
) -> None:
    admin = setup(harness)
    headers = bearer(str(admin["access_token"]))
    company_id = str(admin["company"]["id"])
    with harness.session_factory() as db:
        vendor = Vendor(
            company_id=company_id,
            name="Reconciliation Vendor",
            slug="reconciliation-vendor",
            status="active",
        )
        customer = Customer(company_id=company_id, full_name="Reconciliation Customer")
        db.add_all([vendor, customer])
        db.flush()
        order = Order(
            company_id=company_id,
            customer_id=customer.id,
            order_number="RECON-ORDER-1",
            status="completed",
            total_minor=300,
            paid_minor=300,
            payment_status="paid",
        )
        db.add(order)
        db.flush()
        payment = Payment(
            company_id=company_id,
            order_id=order.id,
            amount_minor=300,
            currency="PKR",
            method="cash",
            status="paid",
        )
        settlement = VendorSettlement(
            company_id=company_id,
            vendor_id=vendor.id,
            settlement_number="RECON-SETTLEMENT-1",
            status="paid",
            payable_minor=500,
            paid_minor=500,
        )
        db.add_all([payment, settlement])
        db.commit()
        vendor_id = vendor.id
        payment_id = payment.id
        settlement_id = settlement.id

    accounts_response = harness.client.get("/api/v1/ledger/accounts", headers=headers)
    accounts = {row["code"]: row for row in accounts_response.json()}
    posted = harness.client.post(
        "/api/v1/ledger/journals",
        headers=headers,
        json={
            "source_type": "settlement",
            "source_id": settlement_id,
            "idempotency_key": f"settlement:{settlement_id}",
            "memo": "Deliberately mismatched settlement for reconciliation test",
            "lines": [
                {
                    "account_id": accounts["2000"]["id"],
                    "vendor_id": vendor_id,
                    "debit_minor": 100,
                },
                {"account_id": accounts["1010"]["id"], "credit_minor": 100},
            ],
        },
    )
    assert posted.status_code == 201, posted.text

    response = harness.client.get("/api/v1/ledger/reconciliation", headers=headers)
    assert response.status_code == 200
    issues = response.json()
    assert any(
        row["issue_type"] == "missing_ledger_posting" and row["source_id"] == payment_id
        for row in issues
    )
    assert any(
        row["issue_type"] == "settlement_ledger_mismatch" and row["source_id"] == settlement_id
        for row in issues
    )


def test_public_registration_page_is_separate_and_csrf_protected(harness: Harness) -> None:
    setup(harness)
    page = harness.client.get("/register?workspace=ledger-test")
    assert page.status_code == 200
    assert "Vendor registration" in page.text
    blocked = harness.client.post(
        "/register",
        data={
            "csrf_token": "invalid",
            "workspace_slug": "ledger-test",
            "business_name": "Web Vendor",
            "username": "web_vendor",
            "email": "web-vendor@example.com",
            "password": "vendor12345",
        },
    )
    assert blocked.status_code == 403
    forgot = harness.client.get("/forgot-password?workspace=ledger-test")
    assert forgot.status_code == 200
    assert "Request password reset" in forgot.text
    csrf = harness.client.cookies.get("erp_csrf")
    assert csrf
    requested = harness.client.post(
        "/forgot-password",
        data={
            "csrf_token": csrf,
            "workspace_slug": "ledger-test",
            "username_or_email": "unknown-user@example.com",
        },
    )
    assert requested.status_code == 202
    assert "If the account exists" in requested.text


def test_vendor_self_service_catalog_stock_and_item_fulfilment(harness: Harness) -> None:
    admin = setup(harness)
    admin_headers = bearer(str(admin["access_token"]))
    registration = harness.client.post(
        "/api/v1/auth/register/vendor",
        json={
            "workspace_slug": "ledger-test",
            "business_name": "Self Service Shop",
            "username": "self_service_vendor",
            "email": "self-service@example.com",
            "password": "vendor12345",
        },
    ).json()
    assert (
        harness.client.post(
            f"/api/v1/marketplace/vendors/{registration['vendor_id']}/approve",
            headers=admin_headers,
        ).status_code
        == 200
    )
    vendor_login = harness.client.post(
        "/api/v1/auth/login",
        json={
            "workspace_slug": "ledger-test",
            "username": "self_service_vendor",
            "password": "vendor12345",
        },
    )
    assert vendor_login.status_code == 200
    vendor_headers = bearer(str(vendor_login.json()["access_token"]))
    assert {"vendor.products.manage", "vendor.orders.manage", "vendor.stock.manage"} <= set(
        vendor_login.json()["permissions"]
    )

    product = harness.client.post(
        "/api/v1/vendor/catalog/products",
        headers=vendor_headers,
        json={"name": "Vendor Live Product", "regular_price_minor": 2500},
    )
    assert product.status_code == 201, product.text
    product_body = product.json()
    assert product_body["status"] == "active"
    assert product_body["visibility"] == "visible"
    assert product_body["vendor_id"] == registration["vendor_id"]
    vendor_video = harness.client.patch(
        f"/api/v1/vendor/catalog/products/{product_body['id']}",
        headers=vendor_headers,
        json={"videos": [{"url": "https://vimeo.com/123456", "sort_order": 0}]},
    )
    assert vendor_video.status_code == 200, vendor_video.text
    assert vendor_video.json()["videos"][0]["source_type"] == "vimeo"
    vendor_upload = harness.client.post(
        f"/api/v1/vendor/catalog/products/{product_body['id']}/videos/upload",
        headers=vendor_headers,
        files={"file": ("vendor.mp4", b"video", "video/mp4")},
    )
    assert vendor_upload.status_code == 201, vendor_upload.text
    unowned_product = harness.client.post(
        "/api/v1/catalog/products",
        headers=admin_headers,
        json={"name": "Admin-only product", "regular_price_minor": 100},
    ).json()
    forbidden_video_upload = harness.client.post(
        f"/api/v1/vendor/catalog/products/{unowned_product['id']}/videos/upload",
        headers=vendor_headers,
        files={"file": ("forbidden.mp4", b"video", "video/mp4")},
    )
    assert forbidden_video_upload.status_code == 404
    assert "Vendor Live Product" in harness.client.get("/store/ledger-test").text
    assert "Self Service Shop" in harness.client.get("/store/ledger-test").text
    assert (
        "Vendor Live Product"
        in harness.client.get("/store/ledger-test/vendors/self-service-shop").text
    )

    warehouse = harness.client.post(
        "/api/v1/inventory/warehouses",
        headers=admin_headers,
        json={"code": "MAIN", "name": "Main Warehouse"},
    ).json()
    movement = harness.client.post(
        "/api/v1/vendor/stock/movements",
        headers=vendor_headers,
        json={
            "vendor_id": "another-vendor-is-ignored",
            "product_id": product_body["id"],
            "warehouse_id": warehouse["id"],
            "movement_type": "opening_balance",
            "quantity_delta": 10,
            "ownership_type": "vendor_owned",
            "source_type": "test",
            "source_id": "opening-1",
            "idempotency_key": "self-service-opening-1",
            "reason": "Initial stock",
        },
    )
    assert movement.status_code == 201, movement.text
    assert movement.json()["vendor_id"] == registration["vendor_id"]

    customer = harness.client.post(
        "/api/v1/customers",
        headers=admin_headers,
        json={"full_name": "Marketplace Customer", "email": "buyer@example.com"},
    ).json()
    order = harness.client.post(
        "/api/v1/orders",
        headers=admin_headers,
        json={
            "customer_id": customer["id"],
            "items": [{"product_id": product_body["id"], "quantity": 1}],
        },
    )
    assert order.status_code == 201, order.text
    # The vendor's Online Orders queue now intentionally contains only
    # WooCommerce orders; this plain ERP order remains available to admins for
    # operational review but is not mixed into the vendor's POS/online views.
    vendor_item = harness.client.get(
        f"/api/v1/marketplace/vendors/{registration['vendor_id']}/order-items",
        headers=admin_headers,
        params={"sales_channel": "legacy"},
    ).json()[0]
    accepted = harness.client.post(
        f"/api/v1/vendor/order-items/{vendor_item['id']}/status",
        headers=vendor_headers,
        json={"status": "accepted"},
    )
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["status"] == "accepted"
    assert (
        harness.client.get(f"/api/v1/orders/{order.json()['id']}", headers=admin_headers).json()[
            "status"
        ]
        == "pending"
    )
    history = harness.client.get(
        f"/api/v1/vendor/order-items/{vendor_item['id']}/history", headers=vendor_headers
    )
    assert history.status_code == 200
    assert history.json()[0]["from_status"] == "pending"
    assert history.json()[0]["to_status"] == "accepted"
