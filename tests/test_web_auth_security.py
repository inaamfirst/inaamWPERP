from __future__ import annotations

import os
import re
import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient
from sqlalchemy.engine import URL, make_url
from sqlalchemy.orm import Session, sessionmaker

from erp.apps.api import web
from erp.apps.api.main import create_app
from erp.apps.api.web import (
    ACCESS_COOKIE,
    ACTIVATION_COOKIE,
    CSRF_COOKIE,
    REFRESH_COOKIE,
    RESET_COOKIE,
)
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
from erp.packages.core.security import hash_password, hash_session_token
from erp.packages.core.services import (
    auth_throttle_scope_keys,
    create_action_token,
    utcnow,
)


@dataclass(frozen=True)
class WebHarness:
    backend: str
    client: TestClient
    session_factory: sessionmaker
    settings: Settings


WEB_AUTH_TABLES = [
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
    return os.environ.get("ERP_TEST_POSTGRES_URL", "").strip() or None


def _session_factory(engine: sa.Engine) -> sessionmaker:
    return sessionmaker(
        bind=engine,
        autoflush=False,
        autocommit=False,
        expire_on_commit=False,
        future=True,
    )


@pytest.fixture(params=("sqlite", "postgresql"))
def web_harness(
    request: pytest.FixtureRequest,
    tmp_path: Path,
) -> Iterator[WebHarness]:
    backend = str(request.param)
    admin_engine: sa.Engine | None = None
    schema: str | None = None
    if backend == "sqlite":
        settings = Settings(
            database_url=f"sqlite:///{tmp_path / 'web_auth.db'}",
            secret_key="phase4a-development-web-secret",
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
        schema = f"phase4a_web_{uuid.uuid4().hex}"
        assert re.fullmatch(r"phase4a_web_[0-9a-f]{32}", schema)
        admin_engine = sa.create_engine(configured, future=True)
        quoted_schema = admin_engine.dialect.identifier_preparer.quote_schema(schema)
        with admin_engine.begin() as connection:
            connection.execute(sa.text(f"CREATE SCHEMA {quoted_schema}"))
        query = dict(url.query)
        query["options"] = f"-csearch_path={schema}"
        scoped_url: URL = url.set(query=query)
        settings = Settings(
            database_url=scoped_url.render_as_string(hide_password=False),
            secret_key="phase4a-development-web-secret",
            media_upload_dir=str(tmp_path / "media"),
            log_dir=str(tmp_path / "logs"),
        )
        engine = sa.create_engine(scoped_url, future=True, pool_pre_ping=True)

    session_factory = _session_factory(engine)
    try:
        Base.metadata.create_all(engine, tables=WEB_AUTH_TABLES)
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
        with TestClient(app, base_url="http://testserver") as client:
            yield WebHarness(backend, client, session_factory, settings)
        app.dependency_overrides.clear()
    finally:
        engine.dispose()
        if admin_engine is not None and schema is not None:
            assert re.fullmatch(r"phase4a_web_[0-9a-f]{32}", schema)
            quoted_schema = admin_engine.dialect.identifier_preparer.quote_schema(schema)
            with admin_engine.begin() as connection:
                connection.execute(sa.text(f"DROP SCHEMA {quoted_schema} CASCADE"))
            admin_engine.dispose()


def _workspace(harness: WebHarness) -> str:
    return f"web-auth-{harness.backend}"


def _setup(harness: WebHarness) -> dict[str, object]:
    response = harness.client.post(
        "/api/v1/setup/first-use",
        json={
            "company_name": f"Web Auth {harness.backend}",
            "workspace_slug": _workspace(harness),
            "username": "admin",
            "password": "admin12345",
            "email": f"web-admin-{harness.backend}@example.test",
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def _csrf(client: TestClient) -> str:
    token = client.cookies.get(CSRF_COOKIE)
    assert token
    return token


def _web_login(
    harness: WebHarness,
    *,
    username: str = "admin",
    password: str = "admin12345",
    remember_me: bool = False,
    next_url: str = "/account",
) -> sa.RowMapping | object:
    page = harness.client.get(
        "/login",
        params={"workspace": _workspace(harness), "next": next_url},
    )
    assert page.status_code == 200
    data = {
        "csrf_token": _csrf(harness.client),
        "workspace_slug": _workspace(harness),
        "username": username,
        "password": password,
        "next": next_url,
    }
    if remember_me:
        data["remember_me"] = "yes"
    return harness.client.post("/login", data=data, follow_redirects=False)


def _cookie_header(response, name: str) -> str:  # type: ignore[no-untyped-def]
    prefix = f"{name}="
    return next(
        value for value in response.headers.get_list("set-cookie") if value.startswith(prefix)
    )


def _assert_security_headers(response) -> None:  # type: ignore[no-untyped-def]
    assert response.headers["cache-control"].startswith("no-store")
    assert response.headers["referrer-policy"] == "no-referrer"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert "frame-ancestors 'none'" in response.headers["content-security-policy"]
    assert "style-src 'self'" in response.headers["content-security-policy"]
    assert "unsafe-inline" not in response.headers["content-security-policy"]


def test_public_web_theme_is_self_hosted_and_packaged(web_harness: WebHarness) -> None:
    page_response = web_harness.client.get("/login")
    stylesheet = web_harness.client.get("/web-assets/web.css")

    assert page_response.status_code == 200
    assert '<link rel="stylesheet" href="/web-assets/web.css">' in page_response.text
    assert "<style" not in page_response.text
    assert stylesheet.status_code == 200
    assert stylesheet.headers["content-type"].startswith("text/css")
    assert "prefers-reduced-motion" in stylesheet.text


def _expire_access(harness: WebHarness, token: str) -> None:
    with harness.session_factory() as db:
        session = db.scalar(
            sa.select(AuthSession).where(
                AuthSession.token_hash == hash_session_token(token)
            )
        )
        assert session is not None
        session.expires_at = datetime.now(UTC) - timedelta(minutes=1)
        db.commit()


def test_web_login_cookies_safe_redirect_headers_and_bearer_compatibility(
    web_harness: WebHarness,
) -> None:
    initial = _setup(web_harness)
    login_page = web_harness.client.get(
        "/login",
        params={
            "workspace": _workspace(web_harness),
            "next": "https://evil.example/steal",
        },
    )
    assert login_page.status_code == 200
    _assert_security_headers(login_page)
    csrf_header = _cookie_header(login_page, CSRF_COOKIE)
    assert "HttpOnly" in csrf_header and "SameSite=strict" in csrf_header
    assert "Secure" not in csrf_header
    cross_purpose = web_harness.client.post(
        "/register",
        data={
            "csrf_token": _csrf(web_harness.client),
            "workspace_slug": _workspace(web_harness),
            "business_name": "Cross Purpose",
            "username": "cross_purpose",
            "email": f"cross-purpose-{web_harness.backend}@example.test",
            "password": "vendor12345",
        },
    )
    assert cross_purpose.status_code == 403

    login_data = {
        "workspace_slug": _workspace(web_harness),
        "username": "admin",
        "password": "admin12345",
        "next": "https://evil.example/steal",
    }
    missing = web_harness.client.post("/login", data=login_data)
    invalid = web_harness.client.post(
        "/login", data={**login_data, "csrf_token": "invalid"}
    )
    assert missing.status_code == invalid.status_code == 403
    _assert_security_headers(missing)

    login_data["csrf_token"] = _csrf(web_harness.client)
    success = web_harness.client.post(
        "/login",
        data=login_data,
        headers={"X-Forwarded-For": "203.0.113.99"},
        follow_redirects=False,
    )
    assert success.status_code == 303
    assert success.headers["location"] == "/account"
    _assert_security_headers(success)
    access_header = _cookie_header(success, ACCESS_COOKIE)
    refresh_header = _cookie_header(success, REFRESH_COOKIE)
    assert "HttpOnly" in access_header and "SameSite=lax" in access_header
    assert "HttpOnly" in refresh_header and "SameSite=strict" in refresh_header
    assert "Max-Age" not in access_header and "Max-Age" not in refresh_header
    assert "Secure" not in access_header and "Secure" not in refresh_header

    account = web_harness.client.get("/account")
    assert account.status_code == 200
    _assert_security_headers(account)
    assert "Account status" in account.text and "Session" in account.text
    assert web_harness.client.cookies.get(ACCESS_COOKIE) not in account.text
    assert web_harness.client.cookies.get(REFRESH_COOKIE) not in account.text

    with web_harness.session_factory() as db:
        latest_refresh = db.scalar(
            sa.select(AuthRefreshToken).order_by(AuthRefreshToken.created_at.desc())
        )
        assert latest_refresh is not None
        assert latest_refresh.ip_address != "203.0.113.99"

    bearer = web_harness.client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {initial['access_token']}"},
    )
    cookie_only_api = web_harness.client.get("/api/v1/auth/me")
    assert bearer.status_code == 200
    assert cookie_only_api.status_code == 401

    remembered = _web_login(
        web_harness,
        remember_me=True,
        next_url="/account?view=session",
    )
    assert remembered.status_code == 303
    assert remembered.headers["location"] == "/account?view=session"
    assert "Max-Age=" in _cookie_header(remembered, ACCESS_COOKIE)
    assert "Max-Age=" in _cookie_header(remembered, REFRESH_COOKIE)


def test_web_vendor_registration_lifecycle_generic_errors_and_throttle(
    web_harness: WebHarness,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    initial = _setup(web_harness)
    admin_headers = {"Authorization": f"Bearer {initial['access_token']}"}
    registration = web_harness.client.get(
        "/register", params={"workspace": _workspace(web_harness)}
    )
    assert registration.status_code == 200
    _assert_security_headers(registration)
    payload = {
        "csrf_token": _csrf(web_harness.client),
        "workspace_slug": _workspace(web_harness),
        "business_name": "Browser Vendor",
        "username": "browser_vendor",
        "email": f"browser-vendor-{web_harness.backend}@example.test",
        "password": "vendor12345",
        "company_id": "attacker-company",
        "role": "Administrator",
        "permissions": "vendors.manage",
        "status": "active",
    }
    submitted = web_harness.client.post(
        "/register", data=payload, follow_redirects=False
    )
    assert submitted.status_code == 303
    assert submitted.headers["location"] == "/register/success"
    success_page = web_harness.client.get("/register/success")
    assert success_page.status_code == 200
    assert "pending administrator approval" in success_page.text

    with web_harness.session_factory() as db:
        user = db.scalar(sa.select(User).where(User.username == "browser_vendor"))
        assert user is not None and user.account_status == "pending"
        vendor = db.scalar(sa.select(Vendor).join(VendorUser).where(VendorUser.user_id == user.id))
        assert vendor is not None and vendor.status == "pending"
        assert db.scalar(sa.select(AuthSession.id).where(AuthSession.user_id == user.id)) is None
        vendor_id = vendor.id

    duplicate_page = web_harness.client.get(
        "/register", params={"workspace": _workspace(web_harness)}
    )
    assert duplicate_page.status_code == 200
    duplicate = web_harness.client.post(
        "/register",
        data={**payload, "csrf_token": _csrf(web_harness.client)},
    )
    assert duplicate.status_code == 400
    assert "Registration could not be completed" in duplicate.text
    assert "browser_vendor" not in duplicate.text
    assert payload["email"] not in duplicate.text

    pending = _web_login(
        web_harness,
        username="browser_vendor",
        password="vendor12345",
    )
    assert pending.status_code == 403
    assert "Unable to sign in with those credentials" in pending.text
    approved = web_harness.client.post(
        f"/api/v1/marketplace/vendors/{vendor_id}/approve", headers=admin_headers
    )
    assert approved.status_code == 200
    active = _web_login(
        web_harness,
        username="browser_vendor",
        password="vendor12345",
    )
    assert active.status_code == 303
    paused = web_harness.client.post(
        f"/api/v1/marketplace/vendors/{vendor_id}/pause",
        headers=admin_headers,
        json={},
    )
    assert paused.status_code == 200
    paused_login = _web_login(
        web_harness,
        username="browser_vendor",
        password="vendor12345",
    )
    assert paused_login.status_code == 403
    assert "Unable to sign in with those credentials" in paused_login.text
    reactivated = web_harness.client.post(
        f"/api/v1/marketplace/vendors/{vendor_id}/reactivate",
        headers=admin_headers,
        json={},
    )
    assert reactivated.status_code == 200
    stopped = web_harness.client.post(
        f"/api/v1/marketplace/vendors/{vendor_id}/stop",
        headers=admin_headers,
        json={},
    )
    assert stopped.status_code == 200
    stopped_login = _web_login(
        web_harness,
        username="browser_vendor",
        password="vendor12345",
    )
    assert stopped_login.status_code == 403
    assert "Unable to sign in with those credentials" in stopped_login.text

    with web_harness.session_factory() as db:
        for status in ("pending", "paused", "stopped"):
            db.add(
                User(
                    company_id=str(initial["company"]["id"]),
                    username=f"web-account-{status}",
                    email=f"web-account-{status}-{web_harness.backend}@example.test",
                    password_hash=hash_password("account12345"),
                    account_status=status,
                    is_active=True,
                )
            )
        db.commit()
    for status in ("pending", "paused", "stopped"):
        rejected = _web_login(
            web_harness,
            username=f"web-account-{status}",
            password="account12345",
        )
        assert rejected.status_code == 403
        assert "Unable to sign in with those credentials" in rejected.text

    with web_harness.session_factory() as db:
        company = db.get(Company, str(initial["company"]["id"]))
        assert company is not None
        company.status = "paused"
        db.commit()
    inactive_company = _web_login(web_harness)
    assert inactive_company.status_code == 403
    assert "Unable to sign in with those credentials" in inactive_company.text

    monkeypatch.setattr(web, "client_ip", lambda _request: "198.51.100.44")
    blocked_username = "throttled_vendor"
    blocked_scope = auth_throttle_scope_keys(
        action="vendor_registration",
        account_identifier=blocked_username,
        workspace=_workspace(web_harness),
        ip_address="198.51.100.44",
    )[0]
    with web_harness.session_factory() as db:
        db.add(
            LoginThrottle(
                scope_key=blocked_scope,
                failure_count=5,
                window_started_at=utcnow(),
                blocked_until=utcnow() + timedelta(minutes=10),
                updated_at=utcnow(),
            )
        )
        company = db.get(Company, str(initial["company"]["id"]))
        assert company is not None
        company.status = "active"
        db.commit()
    web_harness.client.get("/register", params={"workspace": _workspace(web_harness)})
    throttled = web_harness.client.post(
        "/register",
        data={
            **payload,
            "csrf_token": _csrf(web_harness.client),
            "username": blocked_username,
            "email": f"throttled-{web_harness.backend}@example.test",
        },
    )
    assert throttled.status_code == 429


def test_web_refresh_rotation_logout_and_cookie_clearing(
    web_harness: WebHarness,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _setup(web_harness)
    login = _web_login(web_harness)
    assert login.status_code == 303
    old_access = web_harness.client.cookies.get(ACCESS_COOKIE)
    old_refresh = web_harness.client.cookies.get(REFRESH_COOKIE)
    assert old_access and old_refresh
    _expire_access(web_harness, old_access)

    account = web_harness.client.get("/account")
    assert account.status_code == 401
    assert "Continue your session" in account.text
    refresh_csrf = _csrf(web_harness.client)
    with web_harness.session_factory() as db:
        old_row = db.scalar(
            sa.select(AuthRefreshToken).where(
                AuthRefreshToken.token_hash == hash_session_token(old_refresh)
            )
        )
        assert old_row is not None and old_row.used_at is None

    rotated = web_harness.client.post(
        "/session/refresh",
        data={"csrf_token": refresh_csrf, "next": "/account"},
        follow_redirects=False,
    )
    assert rotated.status_code == 303
    assert rotated.headers["location"] == "/account"
    assert web_harness.client.cookies.get(ACCESS_COOKIE) != old_access
    assert web_harness.client.cookies.get(REFRESH_COOKIE) != old_refresh
    with web_harness.session_factory() as db:
        old_row = db.scalar(
            sa.select(AuthRefreshToken).where(
                AuthRefreshToken.token_hash == hash_session_token(old_refresh)
            )
        )
        assert old_row is not None and old_row.used_at is not None

    logout_page = web_harness.client.get("/logout")
    assert logout_page.status_code == 200
    missing = web_harness.client.post("/logout", data={}, follow_redirects=False)
    invalid = web_harness.client.post(
        "/logout", data={"csrf_token": "invalid"}, follow_redirects=False
    )
    assert missing.status_code == invalid.status_code == 403
    valid = web_harness.client.post(
        "/logout",
        data={"csrf_token": _csrf(web_harness.client)},
        follow_redirects=False,
    )
    assert valid.status_code == 303
    for cookie_name in (ACCESS_COOKIE, REFRESH_COOKIE, CSRF_COOKIE):
        assert f"{cookie_name}=\"\"" in "\n".join(valid.headers.get_list("set-cookie"))
        assert web_harness.client.cookies.get(cookie_name) is None

    refresh_only_login = _web_login(web_harness)
    assert refresh_only_login.status_code == 303
    refresh_only_access = web_harness.client.cookies.get(ACCESS_COOKIE)
    refresh_only_token = web_harness.client.cookies.get(REFRESH_COOKIE)
    assert refresh_only_access and refresh_only_token
    _expire_access(web_harness, refresh_only_access)
    web_harness.client.get("/logout")
    refresh_logout = web_harness.client.post(
        "/logout",
        data={"csrf_token": _csrf(web_harness.client)},
        follow_redirects=False,
    )
    assert refresh_logout.status_code == 303
    with web_harness.session_factory() as db:
        refresh_row = db.scalar(
            sa.select(AuthRefreshToken).where(
                AuthRefreshToken.token_hash == hash_session_token(refresh_only_token)
            )
        )
        assert refresh_row is not None and refresh_row.revoked_at is not None

    failure_login = _web_login(web_harness)
    assert failure_login.status_code == 303
    web_harness.client.get("/logout")

    def fail_revocation(*_args, **_kwargs) -> None:  # type: ignore[no-untyped-def]
        raise RuntimeError("simulated revocation outage")

    monkeypatch.setattr(web, "revoke_session", fail_revocation)
    failure_logout = web_harness.client.post(
        "/logout",
        data={"csrf_token": _csrf(web_harness.client)},
        follow_redirects=False,
    )
    assert failure_logout.status_code == 303
    assert web_harness.client.cookies.get(ACCESS_COOKIE) is None
    assert web_harness.client.cookies.get(REFRESH_COOKIE) is None


def test_web_forgot_reset_activation_are_generic_clean_and_one_time(
    web_harness: WebHarness,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    initial = _setup(web_harness)
    company_id = str(initial["company"]["id"])
    with web_harness.session_factory() as db:
        reset_user = User(
            company_id=company_id,
            username="reset_user",
            email=f"reset-{web_harness.backend}@example.test",
            password_hash=hash_password("before12345"),
            account_status="active",
            is_active=True,
        )
        activation_user = User(
            company_id=company_id,
            username="activation_user",
            email=f"activation-web-{web_harness.backend}@example.test",
            password_hash=hash_password("unavailable12345"),
            account_status="active",
            is_active=True,
            must_change_password=True,
        )
        db.add_all([reset_user, activation_user])
        db.flush()
        activation_token, _row = create_action_token(
            db,
            activation_user,
            "activation",
            metadata={"password_required": True},
        )
        db.commit()

    delivered: dict[str, str] = {}

    def capture_delivery(*, email: str, purpose: str, token: str, settings: Settings) -> bool:
        del settings
        delivered.update(email=email, purpose=purpose, token=token)
        return True

    monkeypatch.setattr(web, "deliver_action_token", capture_delivery)
    known_page = web_harness.client.get(
        "/forgot-password", params={"workspace": _workspace(web_harness)}
    )
    assert known_page.status_code == 200
    known = web_harness.client.post(
        "/forgot-password",
        data={
            "csrf_token": _csrf(web_harness.client),
            "workspace_slug": _workspace(web_harness),
            "username_or_email": "reset_user",
        },
    )
    assert known.status_code == 202
    reset_token = delivered["token"]
    unknown_page = web_harness.client.get(
        "/forgot-password", params={"workspace": _workspace(web_harness)}
    )
    assert unknown_page.status_code == 200
    unknown = web_harness.client.post(
        "/forgot-password",
        data={
            "csrf_token": _csrf(web_harness.client),
            "workspace_slug": _workspace(web_harness),
            "username_or_email": "unknown-user",
        },
    )
    assert unknown.status_code == 202
    assert known.text == unknown.text

    reset_redirect = web_harness.client.get(
        "/reset-password", params={"token": reset_token}, follow_redirects=False
    )
    assert reset_redirect.status_code == 303
    assert reset_redirect.headers["location"] == "/reset-password"
    assert reset_token not in reset_redirect.headers["location"]
    _assert_security_headers(reset_redirect)
    reset_page = web_harness.client.get("/reset-password")
    assert reset_page.status_code == 200
    assert reset_token not in reset_page.text
    reset = web_harness.client.post(
        "/reset-password",
        data={"csrf_token": _csrf(web_harness.client), "password": "after12345"},
    )
    assert reset.status_code == 200
    assert web_harness.client.cookies.get(RESET_COOKIE) is None

    web_harness.client.get(
        "/reset-password", params={"token": reset_token}, follow_redirects=False
    )
    web_harness.client.get("/reset-password")
    reset_reuse = web_harness.client.post(
        "/reset-password",
        data={"csrf_token": _csrf(web_harness.client), "password": "again12345"},
    )
    assert reset_reuse.status_code == 400
    assert "invalid or expired" in reset_reuse.text
    assert "Action token" not in reset_reuse.text

    activation_redirect = web_harness.client.get(
        "/activate", params={"token": activation_token}, follow_redirects=False
    )
    assert activation_redirect.status_code == 303
    assert activation_redirect.headers["location"] == "/activate"
    activation_page = web_harness.client.get("/activate")
    assert activation_page.status_code == 200
    assert activation_token not in activation_page.text
    activated = web_harness.client.post(
        "/activate",
        data={"csrf_token": _csrf(web_harness.client), "password": "activated12345"},
    )
    assert activated.status_code == 200
    assert web_harness.client.cookies.get(ACTIVATION_COOKIE) is None

    web_harness.client.get(
        "/activate", params={"token": activation_token}, follow_redirects=False
    )
    web_harness.client.get("/activate")
    activation_reuse = web_harness.client.post(
        "/activate",
        data={"csrf_token": _csrf(web_harness.client), "password": "again12345"},
    )
    assert activation_reuse.status_code == 400
    assert "invalid or expired" in activation_reuse.text


def test_web_login_reset_and_activation_throttles(
    web_harness: WebHarness,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _setup(web_harness)
    fixed_ip = "198.51.100.77"
    monkeypatch.setattr(web, "client_ip", lambda _request: fixed_ip)

    login_scope = auth_throttle_scope_keys(
        action="login",
        account_identifier="admin",
        workspace=_workspace(web_harness),
        ip_address=fixed_ip,
    )[0]
    forgot_scope = auth_throttle_scope_keys(
        action="password_reset_request",
        account_identifier="forgot-throttled",
        workspace=_workspace(web_harness),
        ip_address=fixed_ip,
    )[0]
    reset_token = "reset-throttled-token-" + ("r" * 48)
    reset_scope = auth_throttle_scope_keys(
        action="password_reset_confirm",
        account_identifier=hash_session_token(reset_token),
        ip_address=fixed_ip,
    )[0]
    activation_token = "activation-throttled-token-" + ("a" * 48)
    activation_scope = auth_throttle_scope_keys(
        action="activation",
        account_identifier=hash_session_token(activation_token),
        ip_address=fixed_ip,
    )[0]
    now = utcnow()
    with web_harness.session_factory() as db:
        for scope_key in (login_scope, forgot_scope, reset_scope, activation_scope):
            db.add(
                LoginThrottle(
                    scope_key=scope_key,
                    failure_count=5,
                    window_started_at=now,
                    blocked_until=now + timedelta(minutes=10),
                    updated_at=now,
                )
            )
        db.commit()

    blocked_login = _web_login(web_harness)
    assert blocked_login.status_code == 429

    web_harness.client.get(
        "/forgot-password", params={"workspace": _workspace(web_harness)}
    )
    blocked_forgot = web_harness.client.post(
        "/forgot-password",
        data={
            "csrf_token": _csrf(web_harness.client),
            "workspace_slug": _workspace(web_harness),
            "username_or_email": "forgot-throttled",
        },
    )
    assert blocked_forgot.status_code == 429

    web_harness.client.get(
        "/reset-password", params={"token": reset_token}, follow_redirects=False
    )
    web_harness.client.get("/reset-password")
    blocked_reset = web_harness.client.post(
        "/reset-password",
        data={"csrf_token": _csrf(web_harness.client), "password": "reset12345"},
    )
    assert blocked_reset.status_code == 429

    web_harness.client.get(
        "/activate", params={"token": activation_token}, follow_redirects=False
    )
    web_harness.client.get("/activate")
    blocked_activation = web_harness.client.post(
        "/activate",
        data={"csrf_token": _csrf(web_harness.client), "password": "activate12345"},
    )
    assert blocked_activation.status_code == 429


def test_production_cookies_are_secure(tmp_path: Path) -> None:
    engine = create_database_engine(
        Settings(database_url=f"sqlite:///{tmp_path / 'production_cookie_data.db'}")
    )
    Base.metadata.create_all(engine, tables=WEB_AUTH_TABLES)
    session_factory = _session_factory(engine)
    settings = Settings(
        env="production",
        api_base_url="https://testserver",
        database_url="postgresql+psycopg://prod_user:StrongPassword@db.example.test/prod",
        secret_key="s" * 64,
        bootstrap_token="b" * 64,
        license_server_admin_key="a" * 64,
        license_offline_signing_key="o" * 64,
        force_https=True,
        trusted_hosts=["testserver"],
        trusted_proxy_ips=["127.0.0.1"],
        worker_loop=True,
        media_upload_dir=str(tmp_path / "media"),
        log_dir=str(tmp_path / "logs"),
    )

    def override_session() -> Iterator[Session]:
        with session_factory() as db:
            yield db

    app = create_app(settings)
    app.dependency_overrides[get_session] = override_session
    try:
        with TestClient(app, base_url="https://testserver") as client:
            login_page = client.get("/login", params={"workspace": "production-web"})
            assert login_page.status_code == 200
            assert "Secure" in _cookie_header(login_page, CSRF_COOKIE)
            setup = client.post(
                "/api/v1/setup/first-use",
                headers={"X-Bootstrap-Token": settings.bootstrap_token},
                json={
                    "company_name": "Production Web",
                    "workspace_slug": "production-web",
                    "username": "admin",
                    "password": "admin12345",
                    "email": "production-web@example.test",
                },
            )
            assert setup.status_code == 200, setup.text
            login_page = client.get("/login", params={"workspace": "production-web"})
            login = client.post(
                "/login",
                data={
                    "csrf_token": _csrf(client),
                    "workspace_slug": "production-web",
                    "username": "admin",
                    "password": "admin12345",
                    "remember_me": "yes",
                },
                follow_redirects=False,
            )
            assert login.status_code == 303
            for name in (ACCESS_COOKIE, REFRESH_COOKIE):
                header = _cookie_header(login, name)
                assert "Secure" in header and "HttpOnly" in header and "Max-Age=" in header
    finally:
        app.dependency_overrides.clear()
        engine.dispose()
