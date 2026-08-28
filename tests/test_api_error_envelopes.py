from __future__ import annotations

from fastapi import Request
from fastapi.testclient import TestClient

from erp.apps.api.main import create_app
from erp.packages.core.config import Settings


def production_settings() -> Settings:
    return Settings(
        env="production",
        secret_key="real-secret-key",
        bootstrap_token="production-bootstrap-token-for-error-tests",
        license_server_admin_key="release-admin-key",
        license_offline_signing_key="release-signing-key",
        database_url=(
            "postgresql+psycopg://erp_app_user:strong-password@db.example.test:5432/erp"
        ),
        api_base_url="https://erp.example.test",
        trusted_hosts=["erp.example.test"],
        force_https=True,
        worker_loop=True,
    )


def assert_diagnostic_envelope(response, *, status_code: int, operation: str) -> None:
    assert response.status_code == status_code
    payload = response.json()
    assert payload["detail"]
    assert payload["operation"] == operation
    assert payload["request_id"] == response.headers["X-Request-ID"]


def test_generic_starlette_404_has_diagnostic_envelope() -> None:
    client = TestClient(create_app())

    response = client.get("/not-a-real-route")

    assert_diagnostic_envelope(
        response,
        status_code=404,
        operation="GET /not-a-real-route",
    )


def test_trusted_host_rejection_has_diagnostic_envelope() -> None:
    client = TestClient(
        create_app(production_settings()),
        base_url="https://erp.example.test",
    )

    response = client.get(
        "/api/v1/health",
        headers={"Host": "untrusted.example.test"},
        follow_redirects=False,
    )

    assert_diagnostic_envelope(
        response,
        status_code=400,
        operation="GET /api/v1/health",
    )


def test_request_size_limit_rejects_oversized_bodies_before_endpoint_processing() -> None:
    app = create_app(Settings(max_request_size_mb=1))
    received_sizes: list[int] = []

    @app.post("/body-check")
    async def body_check(request: Request) -> dict[str, int]:
        body = await request.body()
        received_sizes.append(len(body))
        return {"size": len(body)}

    client = TestClient(app)
    normal_response = client.post("/body-check", content=b"normal")

    assert normal_response.status_code == 200
    assert normal_response.json() == {"size": 6}

    response = client.post("/body-check", content=b"x" * (1024 * 1024 + 1))

    assert_diagnostic_envelope(response, status_code=413, operation="POST /body-check")
    assert response.json()["detail"] == "Request body exceeds the configured maximum size."
    assert received_sizes == [6]
