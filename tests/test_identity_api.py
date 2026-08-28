from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from erp.apps.api.main import create_app
from erp.packages.core.db.base import Base
from erp.packages.core.db.session import get_session
from erp.packages.core.schemas import FirstUseSetupRequest
from erp.packages.core.services import context_from_token, setup_first_use


@pytest.fixture()
def client(tmp_path: Path) -> Iterator[TestClient]:
    engine = create_engine(
        f"sqlite:///{tmp_path / 'identity_api.db'}",
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
        yield test_client
    app.dependency_overrides.clear()


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
            "email": "admin@example.com",
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["token_type"] == "bearer"
    assert payload["company"]["name"] == "ChoiceOye Test Company"
    assert "settings.manage" in payload["permissions"]
    return str(payload["access_token"])


def test_first_use_login_settings_audit_logout_flow(client: TestClient) -> None:
    status = client.get("/api/v1/setup/status")
    assert status.status_code == 200
    assert status.json() == {"is_configured": False}

    token = complete_first_use_setup(client)

    status = client.get("/api/v1/setup/status")
    assert status.json() == {"is_configured": True}

    duplicate_setup = client.post(
        "/api/v1/setup/first-use",
        json={
            "company_name": "Duplicate",
            "username": "another",
            "password": "admin12345",
        },
    )
    assert duplicate_setup.status_code == 409

    me = client.get("/api/v1/auth/me", headers=bearer(token))
    assert me.status_code == 200
    assert me.json()["user"]["username"] == "admin"
    assert me.json()["user"]["role_names"] == ["Administrator"]
    assert len(me.json()["user"]["role_ids"]) == 1

    roles = client.get("/api/v1/identity/roles", headers=bearer(token))
    assert roles.status_code == 200
    assert roles.json()[0]["name"] == "Administrator"
    assert "identity.manage_roles" in roles.json()[0]["permissions"]

    setting = client.put(
        "/api/v1/settings/store.profile",
        headers=bearer(token),
        json={"value": {"timezone": "Asia/Karachi", "currency": "PKR"}},
    )
    assert setting.status_code == 200
    assert setting.json()["value"]["currency"] == "PKR"

    settings = client.get("/api/v1/settings", headers=bearer(token))
    assert settings.status_code == 200
    assert settings.json()[0]["key"] == "store.profile"

    audit_logs = client.get("/api/v1/audit-logs", headers=bearer(token))
    assert audit_logs.status_code == 200
    actions = {entry["action"] for entry in audit_logs.json()}
    assert {"setup.first_use_completed", "settings.updated"}.issubset(actions)

    logout = client.post("/api/v1/auth/logout", headers=bearer(token))
    assert logout.status_code == 200
    assert logout.json() == {"ok": True}

    expired_me = client.get("/api/v1/auth/me", headers=bearer(token))
    assert expired_me.status_code == 401


def test_login_success_and_failure(client: TestClient) -> None:
    complete_first_use_setup(client)

    bad_login = client.post(
        "/api/v1/auth/login",
        json={"username": "admin", "password": "wrong-password"},
    )
    assert bad_login.status_code == 401

    good_login = client.post(
        "/api/v1/auth/login",
        json={"username": "admin", "password": "admin12345"},
    )
    assert good_login.status_code == 200
    assert good_login.json()["user"]["username"] == "admin"


def test_authenticated_context_stays_read_only_during_a_sqlite_write_lock(
    tmp_path: Path,
) -> None:
    """Catalog reads must not become writers while WooCommerce is syncing.

    The previous auth path updated ``auth_sessions.last_seen_at`` for every
    request. A long-running sync owns SQLite's writer lock, so an otherwise
    read-only product click would block behind that lock. This verifies a
    bearer-token lookup remains usable while another connection is writing.
    """

    engine = create_engine(
        f"sqlite:///{tmp_path / 'auth_read_only.db'}",
        connect_args={"check_same_thread": False, "timeout": 0.1},
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

    with session_factory() as setup_db:
        issued = setup_first_use(
            setup_db,
            FirstUseSetupRequest(
                company_name="ChoiceOye Test Company",
                username="admin",
                password="admin12345",
                full_name="Admin User",
                email="admin@example.com",
            ),
        )
        user_id = issued.user.id
        token = issued.token
        setup_db.commit()

    writer = session_factory()
    try:
        writer.execute(text("BEGIN IMMEDIATE"))
        writer.execute(
            text("UPDATE users SET full_name = full_name WHERE id = :user_id"),
            {"user_id": user_id},
        )
        with session_factory() as reader:
            context = context_from_token(reader, token)
            assert context.user.id == user_id
            assert context.session.last_seen_at is None
    finally:
        writer.rollback()
        writer.close()
        engine.dispose()
