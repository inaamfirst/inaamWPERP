from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from erp.apps.api.main import create_app
from erp.packages.core.config import Settings
from erp.packages.core.db.base import Base
from erp.packages.core.db.models import (
    Company,
    Customer,
    CustomerAddress,
    Order,
    Permission,
    Role,
    RolePermission,
    User,
    UserRole,
)
from erp.packages.core.db.session import get_session
from erp.packages.core.security import hash_password


@pytest.fixture()
def delivery_harness(tmp_path: Path) -> Iterator[tuple[TestClient, sessionmaker[Session]]]:
    settings = Settings(
        database_url=f"sqlite:///{tmp_path / 'delivery.db'}",
        media_upload_dir=str(tmp_path / "media"),
        log_dir=str(tmp_path / "logs"),
    )
    engine = create_engine(settings.database_url, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)

    def override_session() -> Iterator[Session]:
        with sessions() as db:
            yield db

    app = create_app(settings)
    app.dependency_overrides[get_session] = override_session
    with TestClient(app) as client:
        yield client, sessions
    app.dependency_overrides.clear()
    engine.dispose()


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def setup_workspace(client: TestClient) -> str:
    response = client.post(
        "/api/v1/setup/first-use",
        json={
            "company_name": "Delivery Test Company",
            "workspace_slug": "delivery-test",
            "username": "admin",
            "password": "admin12345",
        },
    )
    assert response.status_code == 200, response.text
    return str(response.json()["access_token"])


def seed_riders_and_order(sessions: sessionmaker[Session]) -> tuple[str, str, str]:
    with sessions() as db:
        company = db.scalar(select(Company))
        assert company is not None
        permissions = list(
            db.scalars(
                select(Permission).where(
                    Permission.key.in_({"delivery.view_assigned", "delivery.update_assigned"})
                )
            ).all()
        )
        rider_role = db.scalar(
            select(Role).where(Role.company_id == company.id, Role.name == "Rider")
        )
        rider_role_existed = True
        if not rider_role:
            rider_role_existed = False
            rider_role = Role(company_id=company.id, name="Rider", description="Test rider")
            db.add(rider_role)
            
        rider_one = User(
            company_id=company.id,
            username="rider-one",
            email="rider-one@example.test",
            password_hash=hash_password("rider12345"),
            full_name="Rider One",
            account_status="active",
        )
        rider_two = User(
            company_id=company.id,
            username="rider-two",
            email="rider-two@example.test",
            password_hash=hash_password("rider12345"),
            full_name="Rider Two",
            account_status="active",
        )
        db.add_all([rider_one, rider_two])
        db.flush()
        
        db.add_all([
            UserRole(user_id=rider_one.id, role_id=rider_role.id),
            UserRole(user_id=rider_two.id, role_id=rider_role.id)
        ])
        
        if not rider_role_existed:
            db.add_all([
                RolePermission(role_id=rider_role.id, permission_id=permission.id)
                for permission in permissions
            ])
            
        customer = Customer(
            company_id=company.id,
            full_name="Delivery Customer",
            phone="03001234567",
        )
        db.add(customer)
        db.flush()
        db.add(
            CustomerAddress(
                company_id=company.id,
                customer_id=customer.id,
                recipient_name=customer.full_name,
                phone=customer.phone,
                line1="1 Main Street",
                city="Lahore",
                is_default=True,
            )
        )
        order = Order(
            company_id=company.id,
            customer_id=customer.id,
            order_number="ORD-DELIVERY-001",
            status="ready",
            currency="PKR",
            total_minor=2500,
            payment_status="paid",
        )
        db.add(order)
        db.commit()
        return company.slug, rider_one.id, order.id


def login_rider(client: TestClient, workspace: str, username: str) -> str:
    response = client.post(
        "/api/v1/auth/login",
        json={"workspace_slug": workspace, "username": username, "password": "rider12345"},
    )
    assert response.status_code == 200, response.text
    return str(response.json()["access_token"])


def test_admin_assigns_and_rider_updates_delivery(
    delivery_harness: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, sessions = delivery_harness
    admin_token = setup_workspace(client)
    workspace, rider_id, order_id = seed_riders_and_order(sessions)

    assignment = client.post(
        "/api/v1/delivery/admin/assignments",
        headers=bearer(admin_token),
        json={"order_id": order_id, "rider_user_id": rider_id},
    )
    assert assignment.status_code == 201, assignment.text
    assignment_id = assignment.json()["id"]
    assert assignment.json()["address_line1"] == "1 Main Street"

    rider_token = login_rider(client, workspace, "rider-one")
    dashboard = client.get("/api/v1/delivery/rider/dashboard", headers=bearer(rider_token))
    assert dashboard.status_code == 200, dashboard.text
    assert dashboard.json()["summary"]["assigned_count"] == 1

    changed = client.post(
        f"/api/v1/delivery/rider/assignments/{assignment_id}/status",
        headers=bearer(rider_token),
        json={"status": "picked_up"},
    )
    assert changed.status_code == 200, changed.text

    rider_two_token = login_rider(client, workspace, "rider-two")
    forbidden_assignment = client.post(
        f"/api/v1/delivery/rider/assignments/{assignment_id}/status",
        headers=bearer(rider_two_token),
        json={"status": "out_for_delivery"},
    )
    assert forbidden_assignment.status_code == 404


def test_assignment_requires_a_default_address(
    delivery_harness: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, sessions = delivery_harness
    admin_token = setup_workspace(client)
    _workspace, rider_id, _order_id = seed_riders_and_order(sessions)
    with sessions() as db:
        company = db.scalar(select(Company))
        assert company is not None
        customer = Customer(company_id=company.id, full_name="No Address Customer")
        db.add(customer)
        db.flush()
        order = Order(
            company_id=company.id,
            customer_id=customer.id,
            order_number="ORD-DELIVERY-002",
            status="ready",
            currency="PKR",
            total_minor=1000,
        )
        db.add(order)
        db.commit()
        order_id = order.id

    response = client.post(
        "/api/v1/delivery/admin/assignments",
        headers=bearer(admin_token),
        json={"order_id": order_id, "rider_user_id": rider_id},
    )
    assert response.status_code == 422
    assert "default address" in response.json()["detail"]
