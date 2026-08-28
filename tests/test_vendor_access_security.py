from __future__ import annotations

import os
import re
import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient
from sqlalchemy.engine import URL, make_url
from sqlalchemy.orm import Session, sessionmaker

from erp.apps.api.main import create_app
from erp.packages.core.config import Settings
from erp.packages.core.db.base import Base
from erp.packages.core.db.models import (
    AuditLog,
    AuthActionToken,
    AuthRefreshToken,
    AuthSession,
    Company,
    LoginThrottle,
    Permission,
    Role,
    RolePermission,
    User,
    UserRole,
    Vendor,
    VendorUser,
)
from erp.packages.core.db.session import create_database_engine, get_session
from erp.packages.core.security import hash_password, verify_password
from erp.packages.core.services import get_user_permissions
from erp.packages.core.vendor_auth_services import (
    VENDOR_PORTAL_PERMISSIONS,
    ensure_vendor_role,
)


@dataclass(frozen=True)
class VendorHarness:
    backend: str
    client: TestClient
    session_factory: sessionmaker


VENDOR_AUTH_TABLES = [
    Company.__table__,
    User.__table__,
    Role.__table__,
    Permission.__table__,
    UserRole.__table__,
    RolePermission.__table__,
    AuthSession.__table__,
    AuthRefreshToken.__table__,
    AuthActionToken.__table__,
    LoginThrottle.__table__,
    Vendor.__table__,
    VendorUser.__table__,
    AuditLog.__table__,
]


def _postgres_test_url() -> str | None:
    value = os.environ.get("ERP_TEST_POSTGRES_URL", "").strip()
    return value or None


@pytest.fixture(params=("sqlite", "postgresql"))
def vendor_harness(
    request: pytest.FixtureRequest,
    tmp_path: Path,
) -> Iterator[VendorHarness]:
    backend = str(request.param)
    admin_engine: sa.Engine | None = None
    schema: str | None = None

    if backend == "sqlite":
        settings = Settings(
            database_url=f"sqlite:///{tmp_path / 'vendor_access.db'}",
            media_upload_dir=str(tmp_path / "media"),
            log_dir=str(tmp_path / "logs"),
        )
        engine = create_database_engine(settings)
    else:
        configured = _postgres_test_url()
        if not configured:
            pytest.skip("ERP_TEST_POSTGRES_URL is not configured")
        url = make_url(configured)
        if not url.drivername.startswith("postgresql"):
            pytest.fail("ERP_TEST_POSTGRES_URL must use PostgreSQL")
        schema = f"phase3_vendor_{uuid.uuid4().hex}"
        assert re.fullmatch(r"phase3_vendor_[0-9a-f]{32}", schema)
        admin_engine = sa.create_engine(configured, future=True)
        quoted_schema = admin_engine.dialect.identifier_preparer.quote_schema(schema)
        with admin_engine.begin() as connection:
            connection.execute(sa.text(f"CREATE SCHEMA {quoted_schema}"))
        query = dict(url.query)
        query["options"] = f"-csearch_path={schema}"
        scoped_url: URL = url.set(query=query)
        settings = Settings(
            database_url=scoped_url.render_as_string(hide_password=False),
            media_upload_dir=str(tmp_path / "media"),
            log_dir=str(tmp_path / "logs"),
        )
        engine = sa.create_engine(scoped_url, future=True, pool_pre_ping=True)

    session_factory = sessionmaker(
        bind=engine,
        autoflush=False,
        autocommit=False,
        expire_on_commit=False,
        future=True,
    )
    try:
        Base.metadata.create_all(engine, tables=VENDOR_AUTH_TABLES)
        forbidden = {
            name
            for name in sa.inspect(engine).get_table_names()
            if name.startswith("ledger_") or name.startswith("vendor_inventory_")
        }
        assert forbidden == set()

        def override_session() -> Iterator[Session]:
            with session_factory() as db:
                yield db

        app = create_app(settings)
        app.dependency_overrides[get_session] = override_session
        with TestClient(app) as client:
            yield VendorHarness(
                backend=backend,
                client=client,
                session_factory=session_factory,
            )
        app.dependency_overrides.clear()
    finally:
        engine.dispose()
        if admin_engine is not None and schema is not None:
            assert re.fullmatch(r"phase3_vendor_[0-9a-f]{32}", schema)
            quoted_schema = admin_engine.dialect.identifier_preparer.quote_schema(schema)
            with admin_engine.begin() as connection:
                connection.execute(sa.text(f"DROP SCHEMA {quoted_schema} CASCADE"))
            admin_engine.dispose()


def _bearer(token: object) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _setup(harness: VendorHarness) -> dict[str, object]:
    response = harness.client.post(
        "/api/v1/setup/first-use",
        json={
            "company_name": f"Vendor Access {harness.backend}",
            "workspace_slug": f"vendor-access-{harness.backend}",
            "username": "admin",
            "password": "admin12345",
            "email": f"admin-{harness.backend}@example.test",
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def _registration_payload(harness: VendorHarness, suffix: str = "") -> dict[str, str]:
    marker = f"-{suffix}" if suffix else ""
    return {
        "workspace_slug": f"vendor-access-{harness.backend}",
        "business_name": f"Public Vendor {suffix or 'Primary'}",
        "username": f"public_vendor{marker}",
        "email": f"public-vendor{marker}-{harness.backend}@example.test",
        "password": "vendor12345",
    }


def _register(harness: VendorHarness, suffix: str = "") -> dict[str, object]:
    response = harness.client.post(
        "/api/v1/auth/register/vendor",
        json=_registration_payload(harness, suffix),
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_public_registration_is_pending_scoped_and_non_enumerating(
    vendor_harness: VendorHarness,
) -> None:
    initial = _setup(vendor_harness)
    payload = _registration_payload(vendor_harness)
    forbidden_payload = {
        **payload,
        "company_id": initial["company"]["id"],
        "role": "Administrator",
        "permissions": ["vendors.manage"],
        "status": "active",
    }
    forbidden = vendor_harness.client.post(
        "/api/v1/auth/register/vendor", json=forbidden_payload
    )
    assert forbidden.status_code == 422

    registered = _register(vendor_harness)
    assert registered["account_status"] == "pending"
    assert registered["vendor_status"] == "pending"

    with vendor_harness.session_factory() as db:
        user = db.get(User, str(registered["user_id"]))
        vendor = db.get(Vendor, str(registered["vendor_id"]))
        assert user is not None and vendor is not None
        assert user.company_id == initial["company"]["id"] == vendor.company_id
        assert user.account_status == vendor.status == "pending"
        assert verify_password(payload["password"], user.password_hash)
        assert db.scalar(sa.select(AuthSession.id).where(AuthSession.user_id == user.id)) is None
        link = db.scalar(sa.select(VendorUser).where(VendorUser.user_id == user.id))
        assert link is not None and link.is_primary and link.vendor_id == vendor.id
        role = db.scalar(
            sa.select(Role)
            .join(UserRole, UserRole.role_id == Role.id)
            .where(UserRole.user_id == user.id)
        )
        assert role is not None and role.name == "Vendor" and role.company_id == user.company_id

    duplicate_username = vendor_harness.client.post(
        "/api/v1/auth/register/vendor",
        json={**payload, "email": f"different-{vendor_harness.backend}@example.test"},
    )
    duplicate_email = vendor_harness.client.post(
        "/api/v1/auth/register/vendor",
        json={**payload, "username": "different_vendor"},
    )
    assert duplicate_username.status_code == duplicate_email.status_code == 409
    assert duplicate_username.json()["detail"] == duplicate_email.json()["detail"]
    assert "username" not in duplicate_username.text.lower()
    assert "email" not in duplicate_email.text.lower()

    pending_login = vendor_harness.client.post(
        "/api/v1/auth/login",
        json={
            "workspace_slug": payload["workspace_slug"],
            "username": payload["username"],
            "password": payload["password"],
        },
    )
    assert pending_login.status_code == 403


def test_registration_uses_phase2_ip_throttle(vendor_harness: VendorHarness) -> None:
    _setup(vendor_harness)
    for index in range(5):
        response = vendor_harness.client.post(
            "/api/v1/auth/register/vendor",
            json=_registration_payload(vendor_harness, f"throttle-{index}"),
        )
        assert response.status_code == 201, response.text
    blocked = vendor_harness.client.post(
        "/api/v1/auth/register/vendor",
        json=_registration_payload(vendor_harness, "throttle-blocked"),
    )
    assert blocked.status_code == 429


def test_administrator_vendor_onboarding_flows_do_not_expose_secrets(
    vendor_harness: VendorHarness,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    initial = _setup(vendor_harness)
    headers = _bearer(initial["access_token"])

    temporary = vendor_harness.client.post(
        "/api/v1/marketplace/vendors/with-account",
        headers=headers,
        json={
            "business_name": "Temporary Password Vendor",
            "username": "temporary_vendor",
            "email": f"temporary-{vendor_harness.backend}@example.test",
            "password": "temporary12345",
            "use_activation": False,
        },
    )
    assert temporary.status_code == 201, temporary.text
    temporary_body = temporary.json()
    assert temporary_body["vendor"]["status"] == "active"
    assert temporary_body["vendor"]["access_status"] == "active"
    assert temporary_body["user"]["account_status"] == "active"
    assert temporary_body["user"]["must_change_password"] is True
    assert temporary_body["activation_token"] is None
    assert temporary_body["onboarding_method"] == "temporary_password"
    assert temporary_body["activation_delivery"] == "not_requested"
    assert temporary_body["user"]["role_names"] == ["Vendor"]
    assert "temporary12345" not in temporary.text

    login = vendor_harness.client.post(
        "/api/v1/auth/login",
        json={
            "workspace_slug": f"vendor-access-{vendor_harness.backend}",
            "username": "temporary_vendor",
            "password": "temporary12345",
        },
    )
    assert login.status_code == 200
    token = login.json()["access_token"]
    assert vendor_harness.client.get(
        "/api/v1/vendor/me", headers=_bearer(token)
    ).status_code == 403
    changed = vendor_harness.client.post(
        "/api/v1/auth/change-password",
        headers=_bearer(token),
        json={
            "current_password": "temporary12345",
            "new_password": "permanent12345",
        },
    )
    assert changed.status_code == 204
    assert vendor_harness.client.get(
        "/api/v1/vendor/me", headers=_bearer(token)
    ).status_code == 200

    delivered: dict[str, str] = {}

    def fake_delivery(*, email: str, purpose: str, token: str, settings: Settings) -> bool:
        del settings
        delivered.update(email=email, purpose=purpose, token=token)
        return True

    monkeypatch.setattr(
        "erp.packages.core.api.marketplace_routes.deliver_action_token",
        fake_delivery,
    )
    activation = vendor_harness.client.post(
        "/api/v1/marketplace/vendors/with-account",
        headers=headers,
        json={
            "business_name": "Activation Vendor",
            "username": "activation_vendor",
            "email": f"activation-{vendor_harness.backend}@example.test",
            "use_activation": True,
        },
    )
    assert activation.status_code == 201, activation.text
    activation_body = activation.json()
    assert activation_body["activation_token"] is None
    assert activation_body["onboarding_method"] == "activation"
    assert activation_body["activation_delivery"] == "sent"
    assert delivered["purpose"] == "activation"
    assert delivered["token"] not in activation.text

    activated = vendor_harness.client.post(
        "/api/v1/auth/activate",
        json={"token": delivered["token"], "password": "activated12345"},
    )
    assert activated.status_code == 204
    activation_login = vendor_harness.client.post(
        "/api/v1/auth/login",
        json={
            "workspace_slug": f"vendor-access-{vendor_harness.backend}",
            "username": "activation_vendor",
            "password": "activated12345",
        },
    )
    assert activation_login.status_code == 200


def test_lifecycle_permissions_session_revocation_and_tenant_isolation(
    vendor_harness: VendorHarness,
) -> None:
    initial = _setup(vendor_harness)
    admin_headers = _bearer(initial["access_token"])
    registered = _register(vendor_harness)
    vendor_id = str(registered["vendor_id"])
    user_id = str(registered["user_id"])
    approved = vendor_harness.client.post(
        f"/api/v1/marketplace/vendors/{vendor_id}/approve",
        headers=admin_headers,
    )
    assert approved.status_code == 200
    assert approved.json()["access_status"] == "active"

    login_payload = {
        "workspace_slug": f"vendor-access-{vendor_harness.backend}",
        "username": "public_vendor",
        "password": "vendor12345",
    }
    login = vendor_harness.client.post("/api/v1/auth/login", json=login_payload)
    assert login.status_code == 200
    vendor_headers = _bearer(login.json()["access_token"])
    assert set(login.json()["permissions"]) == VENDOR_PORTAL_PERMISSIONS

    own = vendor_harness.client.get(
        "/api/v1/vendor/me",
        headers=vendor_headers,
        params={"vendor_id": "ignored-other-vendor"},
    )
    assert own.status_code == 200
    assert own.json()["id"] == vendor_id

    other = vendor_harness.client.post(
        "/api/v1/marketplace/vendors",
        headers=admin_headers,
        json={"name": "Same Company Other", "status": "active"},
    )
    assert other.status_code == 201
    other_vendor_id = str(other.json()["id"])
    company_id = str(initial["company"]["id"])
    with vendor_harness.session_factory() as db:
        foreign_company = Company(
            name="Foreign Company",
            slug=f"foreign-{vendor_harness.backend}",
            status="active",
        )
        db.add(foreign_company)
        db.flush()
        foreign_vendor = Vendor(
            company_id=foreign_company.id,
            name="Foreign Vendor",
            slug="foreign-vendor",
            status="active",
        )
        db.add(foreign_vendor)
        admin = db.get(User, str(initial["user"]["id"]))
        assert admin is not None
        db.add(
            VendorUser(
                company_id=company_id,
                vendor_id=other_vendor_id,
                user_id=admin.id,
                role_name="historical",
                is_primary=True,
            )
        )
        db.commit()
        foreign_vendor_id = foreign_vendor.id

    assert vendor_harness.client.get(
        "/api/v1/marketplace/vendors", headers=vendor_headers
    ).status_code == 403
    assert vendor_harness.client.get(
        f"/api/v1/marketplace/vendors/{other_vendor_id}", headers=vendor_headers
    ).status_code == 403
    assert vendor_harness.client.patch(
        f"/api/v1/marketplace/vendors/{other_vendor_id}/status",
        headers=vendor_headers,
        json={"status": "stopped"},
    ).status_code == 403
    assert vendor_harness.client.post(
        "/api/v1/marketplace/settlements",
        headers=vendor_headers,
        json={"vendor_id": other_vendor_id},
    ).status_code == 403
    assert vendor_harness.client.get(
        "/api/v1/identity/roles", headers=vendor_headers
    ).status_code == 403
    assert vendor_harness.client.get(
        f"/api/v1/marketplace/vendors/{foreign_vendor_id}", headers=admin_headers
    ).status_code == 404

    paused = vendor_harness.client.post(
        f"/api/v1/marketplace/vendors/{vendor_id}/pause",
        headers=admin_headers,
        json={"reason": "Compliance review"},
    )
    assert paused.status_code == 200
    assert paused.json()["status"] == paused.json()["access_status"] == "paused"
    assert vendor_harness.client.get(
        "/api/v1/vendor/me", headers=vendor_headers
    ).status_code == 401
    with vendor_harness.session_factory() as db:
        user = db.get(User, user_id)
        assert user is not None and user.account_status == "active" and user.is_active
    assert vendor_harness.client.post(
        "/api/v1/auth/login", json=login_payload
    ).status_code == 403

    reactivated = vendor_harness.client.post(
        f"/api/v1/marketplace/vendors/{vendor_id}/reactivate",
        headers=admin_headers,
        json={},
    )
    assert reactivated.status_code == 200
    assert reactivated.json()["access_status"] == "active"
    second_login = vendor_harness.client.post(
        "/api/v1/auth/login", json=login_payload
    )
    assert second_login.status_code == 200
    stopped = vendor_harness.client.post(
        f"/api/v1/marketplace/vendors/{vendor_id}/stop",
        headers=admin_headers,
        json={"reason": "Contract ended"},
    )
    assert stopped.status_code == 200
    assert stopped.json()["access_status"] == "stopped"
    assert vendor_harness.client.get(
        "/api/v1/auth/me", headers=_bearer(second_login.json()["access_token"])
    ).status_code == 401
    assert vendor_harness.client.get(
        "/api/v1/auth/me", headers=admin_headers
    ).status_code == 200


def test_legacy_status_aliases_and_ambiguous_links_fail_closed(
    vendor_harness: VendorHarness,
) -> None:
    initial = _setup(vendor_harness)
    admin_headers = _bearer(initial["access_token"])
    company_id = str(initial["company"]["id"])
    with vendor_harness.session_factory() as db:
        legacy_active = Vendor(
            company_id=company_id,
            name="Legacy Approved",
            slug="legacy-approved",
            status="approved",
        )
        legacy_paused = Vendor(
            company_id=company_id,
            name="Legacy Suspended",
            slug="legacy-suspended",
            status="suspended",
        )
        legacy_stopped = Vendor(
            company_id=company_id,
            name="Legacy Rejected",
            slug="legacy-rejected",
            status="rejected",
        )
        db.add_all([legacy_active, legacy_paused, legacy_stopped])
        db.commit()
        legacy_active_id = legacy_active.id
        legacy_paused_id = legacy_paused.id
        legacy_stopped_id = legacy_stopped.id

    detail = vendor_harness.client.get(
        f"/api/v1/marketplace/vendors/{legacy_active_id}", headers=admin_headers
    )
    assert detail.status_code == 200
    assert detail.json()["status"] == "approved"
    assert detail.json()["access_status"] == "active"
    active_rows = vendor_harness.client.get(
        "/api/v1/marketplace/vendors",
        headers=admin_headers,
        params={"status": "approved"},
    )
    assert active_rows.status_code == 200
    assert legacy_active_id in {row["id"] for row in active_rows.json()}

    paused = vendor_harness.client.patch(
        f"/api/v1/marketplace/vendors/{legacy_paused_id}/status",
        headers=admin_headers,
        json={"status": "suspended"},
    )
    stopped = vendor_harness.client.patch(
        f"/api/v1/marketplace/vendors/{legacy_stopped_id}/status",
        headers=admin_headers,
        json={"status": "rejected"},
    )
    assert paused.status_code == stopped.status_code == 200
    assert paused.json()["status"] == paused.json()["access_status"] == "paused"
    assert stopped.json()["status"] == stopped.json()["access_status"] == "stopped"
    with vendor_harness.session_factory() as db:
        untouched = db.get(Vendor, legacy_active_id)
        assert untouched is not None and untouched.status == "approved"

    registered = _register(vendor_harness, "ambiguous")
    approved = vendor_harness.client.post(
        f"/api/v1/marketplace/vendors/{registered['vendor_id']}/approve",
        headers=admin_headers,
    )
    assert approved.status_code == 200
    login = vendor_harness.client.post(
        "/api/v1/auth/login",
        json={
            "workspace_slug": f"vendor-access-{vendor_harness.backend}",
            "username": "public_vendor-ambiguous",
            "password": "vendor12345",
        },
    )
    assert login.status_code == 200
    with vendor_harness.session_factory() as db:
        extra_vendor = Vendor(
            company_id=company_id,
            name="Ambiguous Extra",
            slug="ambiguous-extra",
            status="active",
        )
        db.add(extra_vendor)
        db.flush()
        db.add(
            VendorUser(
                company_id=company_id,
                vendor_id=extra_vendor.id,
                user_id=str(registered["user_id"]),
                role_name="vendor",
                is_primary=True,
            )
        )
        db.commit()
    ambiguous = vendor_harness.client.get(
        "/api/v1/vendor/me", headers=_bearer(login.json()["access_token"])
    )
    assert ambiguous.status_code == 409


def test_unambiguous_vendor_role_backfill_is_company_scoped(
    vendor_harness: VendorHarness,
) -> None:
    initial = _setup(vendor_harness)
    company_id = str(initial["company"]["id"])
    with vendor_harness.session_factory() as db:
        vendor = Vendor(
            company_id=company_id,
            name="Backfill Vendor",
            slug="backfill-vendor",
            status="active",
        )
        user = User(
            company_id=company_id,
            username="backfill_vendor",
            email=f"backfill-{vendor_harness.backend}@example.test",
            password_hash=hash_password("vendor12345"),
            account_status="active",
            is_active=True,
        )
        foreign_company = Company(
            name="Backfill Foreign",
            slug=f"backfill-foreign-{vendor_harness.backend}",
            status="active",
        )
        db.add_all([vendor, user, foreign_company])
        db.flush()
        foreign_role = Role(company_id=foreign_company.id, name="Vendor")
        db.add_all(
            [
                foreign_role,
                VendorUser(
                    company_id=company_id,
                    vendor_id=vendor.id,
                    user_id=user.id,
                    role_name="vendor",
                    is_primary=False,
                ),
            ]
        )
        db.flush()
        role = ensure_vendor_role(db, company_id)
        db.commit()

        link = db.scalar(sa.select(VendorUser).where(VendorUser.user_id == user.id))
        assert link is not None and link.is_primary
        assigned_roles = set(
            db.scalars(
                sa.select(Role.name)
                .join(UserRole, UserRole.role_id == Role.id)
                .where(UserRole.user_id == user.id, Role.company_id == company_id)
            ).all()
        )
        assert assigned_roles == {"Vendor"}
        permission_keys = set(
            db.scalars(
                sa.select(Permission.key)
                .join(RolePermission, RolePermission.permission_id == Permission.id)
                .where(RolePermission.role_id == role.id)
            ).all()
        )
        assert permission_keys == VENDOR_PORTAL_PERMISSIONS
        assert role.company_id == company_id and role.id != foreign_role.id

        old_permission = db.scalar(
            sa.select(Permission).where(Permission.key == "ledger.view")
        )
        assert old_permission is not None
        db.add(RolePermission(role_id=role.id, permission_id=old_permission.id))
        db.flush()
        assert "ledger.view" not in get_user_permissions(db, user.id)

        custom_role = Role(company_id=company_id, name="Custom Finance")
        db.add(custom_role)
        db.flush()
        db.add_all(
            [
                UserRole(user_id=user.id, role_id=custom_role.id),
                RolePermission(role_id=custom_role.id, permission_id=old_permission.id),
            ]
        )
        db.flush()
        assert "ledger.view" in get_user_permissions(db, user.id)
