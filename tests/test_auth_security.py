from __future__ import annotations

import os
import re
import uuid
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Barrier

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
    new_uuid,
)
from erp.packages.core.db.session import create_database_engine, get_session
from erp.packages.core.schemas import FirstUseSetupRequest
from erp.packages.core.security import hash_password, hash_session_token, verify_password
from erp.packages.core.services import (
    ServiceError,
    auth_throttle_scope_keys,
    confirm_password_reset,
    create_action_token,
    prune_auth_sessions,
    record_auth_throttle_attempt,
    rotate_refresh_token,
    setup_first_use,
)


@dataclass(frozen=True)
class ApiHarness:
    client: TestClient
    session_factory: sessionmaker


@dataclass(frozen=True)
class ConcurrentDatabase:
    backend: str
    session_factory: sessionmaker


AUTH_TEST_TABLES = [
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


def _session_factory(engine: sa.Engine) -> sessionmaker:
    return sessionmaker(
        bind=engine,
        autoflush=False,
        autocommit=False,
        expire_on_commit=False,
        future=True,
    )


@pytest.fixture()
def api_harness(tmp_path: Path) -> Iterator[ApiHarness]:
    settings = Settings(
        database_url=f"sqlite:///{tmp_path / 'auth_security_api.db'}",
        media_upload_dir=str(tmp_path / "media"),
        log_dir=str(tmp_path / "logs"),
    )
    engine = create_database_engine(settings)
    Base.metadata.create_all(engine, tables=AUTH_TEST_TABLES)
    session_factory = _session_factory(engine)

    def override_session() -> Iterator[Session]:
        with session_factory() as db:
            yield db

    app = create_app(settings)
    app.dependency_overrides[get_session] = override_session
    with TestClient(app) as client:
        yield ApiHarness(client=client, session_factory=session_factory)
    app.dependency_overrides.clear()
    engine.dispose()


def _postgres_test_url() -> str | None:
    value = os.environ.get("ERP_TEST_POSTGRES_URL", "").strip()
    return value or None


@pytest.fixture(params=("sqlite", "postgresql"))
def concurrent_database(
    request: pytest.FixtureRequest,
    tmp_path: Path,
) -> Iterator[ConcurrentDatabase]:
    backend = str(request.param)
    admin_engine: sa.Engine | None = None
    schema: str | None = None

    if backend == "sqlite":
        settings = Settings(database_url=f"sqlite:///{tmp_path / 'concurrency.db'}")
        engine = create_database_engine(settings)
    else:
        configured = _postgres_test_url()
        if not configured:
            pytest.skip("ERP_TEST_POSTGRES_URL is not configured")
        url = make_url(configured)
        if not url.drivername.startswith("postgresql"):
            pytest.fail("ERP_TEST_POSTGRES_URL must use PostgreSQL")
        schema = f"phase2_auth_{uuid.uuid4().hex}"
        assert re.fullmatch(r"phase2_auth_[0-9a-f]{32}", schema)
        admin_engine = sa.create_engine(configured, future=True)
        quoted_schema = admin_engine.dialect.identifier_preparer.quote_schema(schema)
        with admin_engine.begin() as connection:
            connection.execute(sa.text(f"CREATE SCHEMA {quoted_schema}"))
        query = dict(url.query)
        query["options"] = f"-csearch_path={schema}"
        scoped_url: URL = url.set(query=query)
        engine = sa.create_engine(scoped_url, future=True, pool_pre_ping=True)

    try:
        Base.metadata.create_all(engine, tables=AUTH_TEST_TABLES)
        yield ConcurrentDatabase(backend=backend, session_factory=_session_factory(engine))
    finally:
        engine.dispose()
        if admin_engine is not None and schema is not None:
            assert re.fullmatch(r"phase2_auth_[0-9a-f]{32}", schema)
            quoted_schema = admin_engine.dialect.identifier_preparer.quote_schema(schema)
            with admin_engine.begin() as connection:
                connection.execute(sa.text(f"DROP SCHEMA {quoted_schema} CASCADE"))
            admin_engine.dispose()


def _setup_payload(suffix: str = "") -> dict[str, str]:
    return {
        "company_name": f"Auth Security {suffix or 'Company'}",
        "workspace_slug": f"auth-security{('-' + suffix) if suffix else ''}",
        "username": f"admin{suffix}",
        "password": "admin12345",
        "email": f"admin{suffix}@example.test",
    }


def _setup_api(harness: ApiHarness) -> dict[str, object]:
    response = harness.client.post("/api/v1/setup/first-use", json=_setup_payload())
    assert response.status_code == 200, response.text
    return response.json()


def _bearer(token: object) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _direct_setup(db: Session, suffix: str = ""):
    payload = FirstUseSetupRequest(**_setup_payload(suffix))
    return setup_first_use(db, payload, settings=Settings(env="development"))


def test_atomic_concurrent_refresh_has_one_winner_and_reuse_revokes_family(
    concurrent_database: ConcurrentDatabase,
) -> None:
    factory = concurrent_database.session_factory
    with factory() as db:
        issued = _direct_setup(db)
        refresh_token = str(issued.refresh_token)
        refresh_hash = hash_session_token(refresh_token)
        initial_row = db.scalar(
            sa.select(AuthRefreshToken).where(AuthRefreshToken.token_hash == refresh_hash)
        )
        assert initial_row is not None
        family_id = initial_row.family_id
        db.commit()

    barrier = Barrier(2)

    def rotate() -> tuple[str, str | int]:
        with factory() as db:
            barrier.wait(timeout=10)
            try:
                rotated = rotate_refresh_token(db, refresh_token)
                db.commit()
                return "ok", str(rotated.refresh_token)
            except ServiceError as exc:
                if exc.status_code == 401:
                    db.commit()
                else:
                    db.rollback()
                return "error", exc.status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _index: rotate(), range(2)))

    assert [status for status, _value in results].count("ok") == 1
    assert [value for status, value in results if status == "error"] == [401]
    with factory() as db:
        family = list(
            db.scalars(
                sa.select(AuthRefreshToken).where(AuthRefreshToken.family_id == family_id)
            ).all()
        )
        assert len(family) == 2
        assert all(row.revoked_at is not None for row in family)
        sessions = list(
            db.scalars(
                sa.select(AuthSession).where(
                    AuthSession.id.in_([row.session_id for row in family])
                )
            ).all()
        )
        assert sessions and all(row.revoked_at is not None for row in sessions)


def test_action_token_consumption_is_atomic_and_one_time(
    concurrent_database: ConcurrentDatabase,
) -> None:
    factory = concurrent_database.session_factory
    with factory() as db:
        issued = _direct_setup(db)
        token, action = create_action_token(db, issued.user, "password_reset")
        action_id = action.id
        user_id = issued.user.id
        db.commit()

    barrier = Barrier(2)

    def consume(index: int) -> tuple[str, int]:
        with factory() as db:
            barrier.wait(timeout=10)
            try:
                confirm_password_reset(db, token, f"new-password-{index}")
                db.commit()
                return "ok", index
            except ServiceError as exc:
                db.rollback()
                return "error", exc.status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(consume, range(2)))

    winners = [value for status, value in results if status == "ok"]
    assert len(winners) == 1
    assert [value for status, value in results if status == "error"] == [400]
    with factory() as db:
        row = db.get(AuthActionToken, action_id)
        user = db.get(User, user_id)
        assert row is not None and row.consumed_at is not None
        assert user is not None
        assert verify_password(f"new-password-{winners[0]}", user.password_hash)
        with pytest.raises(ServiceError, match="invalid or expired"):
            confirm_password_reset(db, token, "another-password")


def test_concurrent_first_use_creates_exactly_one_administrator(
    concurrent_database: ConcurrentDatabase,
) -> None:
    factory = concurrent_database.session_factory
    barrier = Barrier(2)

    def bootstrap(index: int) -> tuple[str, int]:
        with factory() as db:
            barrier.wait(timeout=10)
            try:
                _direct_setup(db, str(index))
                db.commit()
                return "ok", index
            except ServiceError as exc:
                db.rollback()
                return "error", exc.status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(bootstrap, range(2)))

    assert [status for status, _value in results].count("ok") == 1
    assert [value for status, value in results if status == "error"] == [409]
    with factory() as db:
        assert db.scalar(sa.select(sa.func.count(User.id))) == 1
        assert db.scalar(sa.select(sa.func.count(Company.id))) == 1
        assert db.scalar(
            sa.select(sa.func.count(Role.id)).where(Role.name == "Administrator")
        ) == 1


def test_concurrent_throttle_updates_do_not_lose_attempts(
    concurrent_database: ConcurrentDatabase,
) -> None:
    factory = concurrent_database.session_factory
    scope_keys = auth_throttle_scope_keys(
        action="login",
        account_identifier="concurrent-user",
        workspace="concurrent-workspace",
        ip_address="192.0.2.10",
    )
    barrier = Barrier(8)

    def record(_index: int) -> None:
        with factory() as db:
            barrier.wait(timeout=10)
            record_auth_throttle_attempt(db, scope_keys)
            db.commit()

    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(record, range(8)))

    with factory() as db:
        rows = list(
            db.scalars(
                sa.select(LoginThrottle).where(LoginThrottle.scope_key.in_(scope_keys))
            ).all()
        )
        assert len(rows) == 2
        assert all(row.failure_count == 8 for row in rows)


def test_production_bootstrap_requires_configured_header(tmp_path: Path) -> None:
    bootstrap_token = "production-bootstrap-token-1234567890"
    settings = Settings(
        env="production",
        database_url="postgresql+psycopg://erp_app:secret@db.example.test:5432/erp",
        api_base_url="https://erp.example.test",
        secret_key="production-secret-key-1234567890",
        bootstrap_token=bootstrap_token,
        license_server_admin_key="production-license-admin-key",
        license_offline_signing_key="production-offline-signing-key",
        trusted_hosts=["erp.example.test"],
        trusted_proxy_ips=["127.0.0.1"],
        force_https=True,
        worker_loop=True,
        media_upload_dir=str(tmp_path / "media"),
        log_dir=str(tmp_path / "logs"),
    )
    engine = create_database_engine(
        Settings(database_url=f"sqlite:///{tmp_path / 'production_bootstrap.db'}")
    )
    Base.metadata.create_all(engine, tables=AUTH_TEST_TABLES)
    factory = _session_factory(engine)

    def override_session() -> Iterator[Session]:
        with factory() as db:
            yield db

    app = create_app(settings)
    app.dependency_overrides[get_session] = override_session
    with TestClient(app, base_url="https://erp.example.test") as client:
        assert client.post("/api/v1/setup/first-use", json=_setup_payload()).status_code == 401
        assert client.post(
            "/api/v1/setup/first-use",
            json=_setup_payload(),
            headers={"X-Bootstrap-Token": "wrong-bootstrap-token-value-12345"},
        ).status_code == 401
        success = client.post(
            "/api/v1/setup/first-use",
            json=_setup_payload(),
            headers={"X-Bootstrap-Token": bootstrap_token},
        )
        assert success.status_code == 200, success.text
    engine.dispose()


def test_logout_modes_are_idempotent_and_all_sessions_requires_access_authority(
    api_harness: ApiHarness,
) -> None:
    initial = _setup_api(api_harness)
    access = str(initial["access_token"])
    refresh = str(initial["refresh_token"])

    access_logout = api_harness.client.post("/api/v1/auth/logout", headers=_bearer(access))
    assert access_logout.status_code == 200
    assert access_logout.json() == {"ok": True}
    assert api_harness.client.get("/api/v1/auth/me", headers=_bearer(access)).status_code == 401
    assert api_harness.client.post(
        "/api/v1/auth/refresh", json={"refresh_token": refresh}
    ).status_code == 401

    login = api_harness.client.post(
        "/api/v1/auth/login",
        json={
            "username": "admin",
            "password": "admin12345",
            "workspace_slug": "auth-security",
            "supports_refresh": True,
        },
    ).json()
    with api_harness.session_factory() as db:
        session = db.get(AuthSession, login["session_id"])
        assert session is not None
        session.expires_at = datetime.now(UTC) - timedelta(minutes=1)
        db.commit()

    refresh_only = api_harness.client.post(
        "/api/v1/auth/logout", json={"refresh_token": login["refresh_token"]}
    )
    assert refresh_only.status_code == 200
    assert api_harness.client.post(
        "/api/v1/auth/logout", json={"refresh_token": login["refresh_token"]}
    ).json() == {"ok": True}
    assert api_harness.client.post(
        "/api/v1/auth/refresh", json={"refresh_token": login["refresh_token"]}
    ).status_code == 401

    first = api_harness.client.post(
        "/api/v1/auth/login",
        json={"username": "admin", "password": "admin12345"},
    ).json()
    second = api_harness.client.post(
        "/api/v1/auth/login",
        json={"username": "admin", "password": "admin12345"},
    ).json()
    unauthorized = api_harness.client.post(
        "/api/v1/auth/logout",
        json={"refresh_token": first["refresh_token"], "all_sessions": True},
    )
    assert unauthorized.status_code == 401
    authorized = api_harness.client.post(
        "/api/v1/auth/logout",
        headers=_bearer(first["access_token"]),
        json={"all_sessions": True},
    )
    assert authorized.status_code == 200
    assert api_harness.client.get(
        "/api/v1/auth/me", headers=_bearer(second["access_token"])
    ).status_code == 401


def test_account_company_vendor_eligibility_and_admin_historical_link(
    api_harness: ApiHarness,
) -> None:
    initial = _setup_api(api_harness)
    company_id = str(initial["company"]["id"])
    admin_id = str(initial["user"]["id"])
    admin_access = str(initial["access_token"])

    registration = api_harness.client.post(
        "/api/v1/auth/register/vendor",
        json={
            "workspace_slug": "auth-security",
            "business_name": "Status Vendor",
            "username": "status-vendor",
            "email": "status-vendor@example.test",
            "password": "vendor12345",
        },
    )
    assert registration.status_code == 201
    vendor_id = str(registration.json()["vendor_id"])
    vendor_user_id = str(registration.json()["user_id"])
    vendor_login = {
        "username": "status-vendor",
        "password": "vendor12345",
        "workspace_slug": "auth-security",
    }
    assert api_harness.client.post("/api/v1/auth/login", json=vendor_login).status_code == 403

    with api_harness.session_factory() as db:
        vendor_user = db.get(User, vendor_user_id)
        vendor = db.get(Vendor, vendor_id)
        assert vendor_user is not None and vendor is not None
        vendor_user.account_status = "active"
        vendor.status = "paused"
        admin = db.get(User, admin_id)
        vendor_role = db.scalar(
            sa.select(Role).where(Role.company_id == company_id, Role.name == "Vendor")
        )
        assert admin is not None and vendor_role is not None
        db.add(UserRole(user_id=admin.id, role_id=vendor_role.id))
        db.add(
            VendorUser(
                company_id=company_id,
                vendor_id=vendor.id,
                user_id=admin.id,
                role_name="historical",
                is_primary=True,
            )
        )
        for status in ("pending", "paused", "stopped"):
            db.add(
                User(
                    company_id=company_id,
                    username=f"account-{status}",
                    email=f"account-{status}@example.test",
                    password_hash=hash_password("account12345"),
                    account_status=status,
                    is_active=True,
                )
            )
        db.add(
            User(
                company_id=company_id,
                username="legacy-inactive",
                email="legacy-inactive@example.test",
                password_hash=hash_password("account12345"),
                account_status="active",
                is_active=False,
            )
        )
        db.commit()

    assert api_harness.client.post("/api/v1/auth/login", json=vendor_login).status_code == 403
    with api_harness.session_factory() as db:
        vendor = db.get(Vendor, vendor_id)
        assert vendor is not None
        vendor.status = "stopped"
        db.commit()
    assert api_harness.client.post("/api/v1/auth/login", json=vendor_login).status_code == 403
    assert api_harness.client.get(
        "/api/v1/auth/me", headers=_bearer(admin_access)
    ).status_code == 200
    admin_login = api_harness.client.post(
        "/api/v1/auth/login",
        json={
            "username": "admin",
            "password": "admin12345",
            "workspace_slug": "auth-security",
            "supports_refresh": True,
        },
    )
    assert admin_login.status_code == 200

    for username in ("account-pending", "account-paused", "account-stopped", "legacy-inactive"):
        response = api_harness.client.post(
            "/api/v1/auth/login",
            json={
                "username": username,
                "password": "account12345",
                "workspace_slug": "auth-security",
            },
        )
        assert response.status_code == 403

    admin_payload = admin_login.json()
    with api_harness.session_factory() as db:
        company = db.get(Company, company_id)
        assert company is not None
        company.status = "paused"
        db.commit()
    assert api_harness.client.post(
        "/api/v1/auth/login",
        json={
            "username": "admin",
            "password": "admin12345",
            "workspace_slug": "auth-security",
        },
    ).status_code == 403
    assert api_harness.client.get(
        "/api/v1/auth/me", headers=_bearer(admin_payload["access_token"])
    ).status_code == 401
    assert api_harness.client.post(
        "/api/v1/auth/refresh", json={"refresh_token": admin_payload["refresh_token"]}
    ).status_code == 401


def test_login_registration_reset_and_activation_are_throttled(
    api_harness: ApiHarness,
) -> None:
    _setup_api(api_harness)
    bad_login = {
        "username": "admin",
        "password": "wrong-password",
        "workspace_slug": "auth-security",
    }
    for _index in range(5):
        assert api_harness.client.post("/api/v1/auth/login", json=bad_login).status_code == 401
    assert api_harness.client.post("/api/v1/auth/login", json=bad_login).status_code == 429

    registration = {
        "workspace_slug": "auth-security",
        "business_name": "Throttled Vendor",
        "username": "throttled-vendor",
        "email": "throttled-vendor@example.test",
        "password": "vendor12345",
    }
    assert api_harness.client.post(
        "/api/v1/auth/register/vendor", json=registration
    ).status_code == 201
    for _index in range(4):
        assert api_harness.client.post(
            "/api/v1/auth/register/vendor", json=registration
        ).status_code == 409
    assert api_harness.client.post(
        "/api/v1/auth/register/vendor", json=registration
    ).status_code == 429

    reset_request = {
        "username_or_email": "does-not-exist@example.test",
        "workspace_slug": "auth-security",
    }
    for _index in range(5):
        response = api_harness.client.post(
            "/api/v1/auth/password-reset/request", json=reset_request
        )
        assert response.status_code == 202
        assert response.json() == {
            "message": "If the account exists, a reset link will be sent."
        }
    assert api_harness.client.post(
        "/api/v1/auth/password-reset/request", json=reset_request
    ).status_code == 429

    invalid_token = "invalid-action-token-value-1234567890"
    for endpoint, body in (
        (
            "/api/v1/auth/password-reset/confirm",
            {"token": invalid_token, "new_password": "newpass12345"},
        ),
        ("/api/v1/auth/activate", {"token": invalid_token, "password": "newpass12345"}),
    ):
        for _index in range(5):
            assert api_harness.client.post(endpoint, json=body).status_code == 400
        assert api_harness.client.post(endpoint, json=body).status_code == 429

    with api_harness.session_factory() as db:
        rows = list(db.scalars(sa.select(LoginThrottle)).all())
        assert len(rows) >= 10
        assert all("admin" not in row.scope_key for row in rows)
        assert all("127.0.0.1" not in row.scope_key for row in rows)


def test_legacy_client_ttl_existing_session_and_password_hash_compatibility(
    api_harness: ApiHarness,
) -> None:
    initial = _setup_api(api_harness)
    assert api_harness.client.get(
        "/api/v1/auth/me", headers=_bearer(initial["access_token"])
    ).status_code == 200
    with api_harness.session_factory() as db:
        admin = db.scalar(sa.select(User).where(User.username == "admin"))
        assert admin is not None
        original_hash = admin.password_hash

    before = datetime.now(UTC)
    legacy = api_harness.client.post(
        "/api/v1/auth/login",
        json={"username": "admin", "password": "admin12345"},
    )
    assert legacy.status_code == 200
    legacy_expiry = datetime.fromisoformat(legacy.json()["expires_at"])
    assert before + timedelta(hours=11, minutes=50) < legacy_expiry

    refresh_aware = api_harness.client.post(
        "/api/v1/auth/login",
        json={
            "username": "admin",
            "password": "admin12345",
            "supports_refresh": True,
        },
    )
    assert refresh_aware.status_code == 200
    refresh_expiry = datetime.fromisoformat(refresh_aware.json()["expires_at"])
    assert before + timedelta(minutes=20) < refresh_expiry < before + timedelta(minutes=40)
    with api_harness.session_factory() as db:
        admin = db.scalar(sa.select(User).where(User.username == "admin"))
        assert admin is not None
        assert admin.password_hash == original_hash


def test_retention_prunes_only_long_expired_authentication_records(
    api_harness: ApiHarness,
) -> None:
    initial = _setup_api(api_harness)
    user_id = str(initial["user"]["id"])
    now = datetime.now(UTC)
    old = now - timedelta(days=200)
    with api_harness.session_factory() as db:
        old_session = AuthSession(
            user_id=user_id,
            token_hash=hash_session_token("old-session-token"),
            expires_at=old,
        )
        active_session = AuthSession(
            user_id=user_id,
            token_hash=hash_session_token("active-session-token"),
            expires_at=now + timedelta(hours=1),
        )
        db.add_all([old_session, active_session])
        db.flush()
        db.add_all(
            [
                AuthRefreshToken(
                    user_id=user_id,
                    session_id=old_session.id,
                    family_id=new_uuid(),
                    token_hash=hash_session_token("old-refresh-token"),
                    expires_at=old,
                ),
                AuthRefreshToken(
                    user_id=user_id,
                    session_id=active_session.id,
                    family_id=new_uuid(),
                    token_hash=hash_session_token("active-refresh-token"),
                    expires_at=now + timedelta(hours=1),
                ),
                AuthActionToken(
                    user_id=user_id,
                    purpose="password_reset",
                    token_hash=hash_session_token("old-action-token"),
                    expires_at=old,
                ),
                AuthActionToken(
                    user_id=user_id,
                    purpose="password_reset",
                    token_hash=hash_session_token("active-action-token"),
                    expires_at=now + timedelta(hours=1),
                ),
                LoginThrottle(
                    scope_key=hash_session_token("old-throttle"),
                    failure_count=5,
                    window_started_at=old,
                    updated_at=old,
                ),
                LoginThrottle(
                    scope_key=hash_session_token("active-throttle"),
                    failure_count=1,
                    window_started_at=now,
                    updated_at=now,
                ),
            ]
        )
        db.commit()

    with api_harness.session_factory() as db:
        prune_auth_sessions(db)
        db.commit()
        session_hashes = set(db.scalars(sa.select(AuthSession.token_hash)).all())
        refresh_hashes = set(db.scalars(sa.select(AuthRefreshToken.token_hash)).all())
        action_hashes = set(db.scalars(sa.select(AuthActionToken.token_hash)).all())
        throttle_hashes = set(db.scalars(sa.select(LoginThrottle.scope_key)).all())
        assert hash_session_token("old-session-token") not in session_hashes
        assert hash_session_token("active-session-token") in session_hashes
        assert hash_session_token("old-refresh-token") not in refresh_hashes
        assert hash_session_token("active-refresh-token") in refresh_hashes
        assert hash_session_token("old-action-token") not in action_hashes
        assert hash_session_token("active-action-token") in action_hashes
        assert hash_session_token("old-throttle") not in throttle_hashes
        assert hash_session_token("active-throttle") in throttle_hashes
