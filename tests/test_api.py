from __future__ import annotations

from fastapi.testclient import TestClient

from erp.apps.api.main import create_app
from erp.packages.core.config import Settings


def production_settings() -> Settings:
    return Settings(
        env="production",
        database_url="postgresql+psycopg://erp_app:strong-password@db.example.test:5432/erp",
        api_base_url="https://erp.example.test",
        secret_key="real-secret-key",
        bootstrap_token="production-bootstrap-token-for-api-tests",
        license_server_admin_key="release-admin-key",
        license_offline_signing_key="release-signing-key",
        trusted_hosts=["erp.example.test"],
        trusted_proxy_ips=["127.0.0.1"],
        force_https=True,
        worker_loop=True,
    )


def test_create_app() -> None:
    app = create_app()

    assert app.title == "Enterprise Commerce ERP"


def test_health_endpoint() -> None:
    client = TestClient(create_app())
    request_id = "health-test-123"

    response = client.get("/api/v1/health", headers={"X-Request-ID": request_id})

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "healthy"
    assert payload["database_configured"] is True
    assert payload["module_count"] == 17
    assert response.headers["X-Request-ID"] == request_id


def test_modules_endpoint() -> None:
    client = TestClient(create_app())

    response = client.get("/api/v1/modules")

    assert response.status_code == 200
    payload = response.json()
    assert payload["count"] == 17
    assert {item["id"] for item in payload["modules"]} >= {
        "accounting",
        "core",
        "marketplace",
        "support",
        "woocommerce",
        "whatsapp",
    }


def test_openapi_docs_load() -> None:
    client = TestClient(create_app())

    response = client.get("/docs")

    assert response.status_code == 200
    assert "swagger-ui" in response.text


def test_production_hides_docs_and_whatsapp_by_default() -> None:
    client = TestClient(create_app(production_settings()), base_url="https://erp.example.test")

    docs = client.get("/docs")
    assert docs.status_code == 404
    assert docs.headers["X-Request-ID"]

    modules = client.get("/api/v1/modules")
    assert modules.status_code == 200
    payload = modules.json()
    assert payload["count"] == 16
    assert "whatsapp" not in {item["id"] for item in payload["modules"]}

    request_id = "whatsapp-disabled-123"
    whatsapp = client.get(
        "/api/v1/whatsapp/templates",
        headers={"X-Request-ID": request_id},
    )
    assert whatsapp.status_code == 404
    assert whatsapp.json() == {
        "detail": "WhatsApp module is disabled.",
        "request_id": request_id,
        "operation": "GET /api/v1/whatsapp/templates",
    }
    assert whatsapp.headers["X-Request-ID"] == request_id


def test_production_can_enable_docs_and_whatsapp_explicitly() -> None:
    settings = production_settings().model_copy(
        update={"docs_enabled": True, "whatsapp_enabled": True}
    )
    client = TestClient(create_app(settings), base_url="https://erp.example.test")

    assert client.get("/docs").status_code == 200
    modules = client.get("/api/v1/modules")
    assert modules.status_code == 200
    assert "whatsapp" in {item["id"] for item in modules.json()["modules"]}


def test_validation_errors_include_safe_request_diagnostics() -> None:
    client = TestClient(create_app())
    request_id = "validation-test-123"

    response = client.post(
        "/api/v1/auth/login",
        json={"username": 12},
        headers={"X-Request-ID": request_id},
    )

    assert response.status_code == 422
    payload = response.json()
    assert payload["detail"] == "Request validation failed."
    assert payload["request_id"] == request_id
    assert payload["operation"] == "POST /api/v1/auth/login"
    assert response.headers["X-Request-ID"] == request_id


def test_unhandled_errors_include_safe_request_diagnostics() -> None:
    app = create_app()

    @app.get("/_test/unhandled-error")
    def unhandled_error() -> None:
        raise RuntimeError("database-password=not-for-clients")

    client = TestClient(app, raise_server_exceptions=False)
    request_id = "unhandled-test-123"
    response = client.get("/_test/unhandled-error", headers={"X-Request-ID": request_id})

    assert response.status_code == 500
    assert response.json() == {
        "detail": "Internal Server Error",
        "request_id": request_id,
        "operation": "GET /_test/unhandled-error",
    }
    assert response.headers["X-Request-ID"] == request_id
