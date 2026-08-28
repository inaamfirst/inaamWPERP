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
from erp.packages.core.db.models import Permission, RolePermission
from erp.packages.core.db.session import get_session


@dataclass(frozen=True)
class ApiHarness:
    client: TestClient
    session_factory: sessionmaker


@dataclass(frozen=True)
class SetupResult:
    token: str
    company_id: str


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture()
def harness(tmp_path: Path) -> Iterator[ApiHarness]:
    engine = create_engine(
        f"sqlite:///{tmp_path / 'permission_backfill.db'}",
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


def complete_first_use_setup(client: TestClient) -> SetupResult:
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
    return SetupResult(
        token=str(payload["access_token"]),
        company_id=str(payload["company"]["id"]),
    )


def test_admin_login_backfills_new_marketplace_permissions(harness: ApiHarness) -> None:
    setup = complete_first_use_setup(harness.client)

    with harness.session_factory() as db:
        vendor_permission_ids = list(
            db.scalars(select(Permission.id).where(Permission.key.like("vendors.%"))).all()
        )
        assert vendor_permission_ids
        db.query(RolePermission).filter(
            RolePermission.permission_id.in_(vendor_permission_ids)
        ).delete(synchronize_session=False)
        db.query(Permission).filter(Permission.key.like("vendors.%")).delete(
            synchronize_session=False
        )
        db.commit()

    vendors_with_existing_token = harness.client.get(
        "/api/v1/marketplace/vendors",
        headers=bearer(setup.token),
    )
    assert vendors_with_existing_token.status_code == 200
    assert vendors_with_existing_token.json() == []

    login = harness.client.post(
        "/api/v1/auth/login",
        json={"username": "admin", "password": "admin12345"},
    )

    assert login.status_code == 200
    assert "vendors.view" in login.json()["permissions"]

    vendors = harness.client.get(
        "/api/v1/marketplace/vendors",
        headers=bearer(str(login.json()["access_token"])),
    )
    assert vendors.status_code == 200
    assert vendors.json() == []
