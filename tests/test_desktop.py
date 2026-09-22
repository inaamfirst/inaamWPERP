from __future__ import annotations

import json

import httpx
import pytest

from erp.apps.desktop import __main__ as desktop_entry
from erp.apps.desktop import main as desktop_main
from erp.apps.desktop.api_client import ApiHealthClient, ApiResponseError


class FakeResponse:
    def __init__(self, payload: object, status_code: int = 200, text: str = "") -> None:
        self.payload = payload
        self.status_code = status_code
        self.text = text
        self.request = httpx.Request("GET", "http://example.test")

    def raise_for_status(self) -> None:
        return None

    def json(self) -> object:
        return self.payload


def test_desktop_main_imports_without_launching_gui() -> None:
    assert callable(desktop_main.run)


def test_desktop_package_smoke_writes_non_gui_marker(tmp_path, monkeypatch) -> None:
    marker = tmp_path / "desktop-smoke.json"
    monkeypatch.setenv("ERP_DESKTOP_SMOKE_FILE", str(marker))
    monkeypatch.setattr(desktop_entry, "package_keyring_smoke", lambda: "test.keyring")

    desktop_entry.package_smoke()

    assert json.loads(marker.read_text(encoding="utf-8")) == {
        "navigation_items": list(desktop_main.navigation_items()),
        "keyring_backend": "test.keyring",
        "keyring_status": "ok",
        "status": "ok",
    }


def test_desktop_navigation_items_cover_v1_screens() -> None:
    assert desktop_main.navigation_items() == (
        "Dashboard",
        "Products",
        "Customers",
        "Inventory",
        "Orders",
        "WooCommerce",
        "Marketplace",
        "Accounting",
        "Settings",
        "Admin",
    )
    assert desktop_main.VENDOR_WORKSPACE_TABS == (
        "Overview",
        "Stock",
        "Stock Movements",
        "Products",
        "Orders / Sales",
        "Financial Ledger",
        "Settlements",
        "Reports",
        "Linked Users",
        "Audit",
    )
    assert desktop_main.LEDGER_WORKSPACE_TABS == (
        "Overview",
        "Chart of Accounts",
        "Journals",
        "Trial Balance",
        "Profit & Loss",
        "Balance Sheet",
        "Cash Flow",
        "Vendor Payables",
        "Inventory",
        "Reconciliation",
    )


def test_operation_notifications_emit_clear_lifecycle_toasts() -> None:
    emitted: list[tuple[str, str]] = []
    notifications = desktop_main.OperationNotifications(
        lambda message, kind: emitted.append((message, kind))
    )

    notifications.show("Saving product", "started")
    notifications.show("Saving product", "running")
    notifications.show("Saving product", "completed")
    notifications.show("Saving product", "failed", "API is offline")

    assert emitted == [
        ("Starting: Saving product", "info"),
        ("Running: Saving product", "running"),
        ("Completed: Saving product", "success"),
        ("Failed: Saving product — API is offline", "error"),
    ]


def test_woocommerce_sync_notifications_only_emit_for_state_changes() -> None:
    assert desktop_main.woocommerce_sync_transition(None, "queued", attempts=1) == (
        "queued",
        "attempt 1",
    )
    assert desktop_main.woocommerce_sync_transition("queued", "queued", attempts=1) is None
    assert desktop_main.woocommerce_sync_transition("queued", "running", attempts=1) == (
        "running",
        "attempt 1",
    )
    assert desktop_main.woocommerce_sync_transition("running", "success", attempts=1) == (
        "completed",
        None,
    )
    assert desktop_main.woocommerce_sync_transition(
        "running",
        "failed",
        attempts=1,
        error="Unauthorized",
    ) == ("failed", "Unauthorized")


def test_woocommerce_sync_completion_message_mentions_archived_products() -> None:
    message, ok = desktop_main.woocommerce_sync_completion_message(
        {"archived_missing_products": 2}
    )

    assert ok is True
    assert message == (
        "WooCommerce sync completed. 2 products were archived locally because they were "
        "deleted online."
    )


def test_woocommerce_sync_running_message_includes_phase() -> None:
    message = desktop_main.woocommerce_sync_running_message(
        {
            "attempts": 3,
            "worker_id": "worker-1",
            "stats": {"current_phase": "Pulling products"},
        }
    )

    assert message == "WooCommerce sync running: Pulling products (attempt 3; worker-1)."


def test_api_health_client_handles_reachable_api(monkeypatch) -> None:
    def fake_request(
        method: str,
        url: str,
        timeout: float,
        headers: dict[str, str] | None = None,
        json: dict[str, object] | None = None,
        params: dict[str, object] | None = None,
        follow_redirects: bool = False,
    ) -> FakeResponse:
        assert method == "GET"
        assert timeout == 2.0
        assert headers is None or headers == {}
        assert json is None
        assert params is None
        assert follow_redirects is True
        assert url.endswith("/api/v1/health")
        return FakeResponse(
            {
                "status": "healthy",
                "app_name": "Enterprise Commerce ERP",
                "module_count": 17,
            }
        )

    monkeypatch.setattr(httpx, "request", fake_request)
    status = ApiHealthClient().get_health()

    assert status.reachable is True
    assert status.status == "healthy"
    assert status.module_count == 17


def test_api_health_client_handles_unreachable_api(monkeypatch) -> None:
    def fake_request(
        method: str,
        url: str,
        timeout: float,
        headers: dict[str, str] | None = None,
        json: dict[str, object] | None = None,
        params: dict[str, object] | None = None,
        follow_redirects: bool = False,
    ) -> FakeResponse:
        assert method == "GET"
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr(httpx, "request", fake_request)
    status = ApiHealthClient().get_health()

    assert status.reachable is False
    assert status.status == "offline"


def test_api_client_wraps_connection_errors(monkeypatch) -> None:
    def fake_request(
        method: str,
        url: str,
        timeout: float,
        headers: dict[str, str] | None = None,
        json: dict[str, object] | None = None,
        params: dict[str, object] | None = None,
        follow_redirects: bool = False,
    ) -> FakeResponse:
        assert method == "POST"
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr(httpx, "request", fake_request)
    client = ApiHealthClient()

    with pytest.raises(ApiResponseError) as excinfo:
        client.request(
            "POST",
            "/api/v1/auth/login",
            json={"username": "admin", "password": "admin12345"},
        )

    assert excinfo.value.status_code == 0
    assert "Unable to connect" in excinfo.value.detail
    assert excinfo.value.url.endswith("/api/v1/auth/login")


def test_api_client_business_methods_use_bearer_token(monkeypatch) -> None:
    calls: list[tuple[str, str, dict[str, str]]] = []

    def fake_request(
        method: str,
        url: str,
        timeout: float,
        headers: dict[str, str],
        json: dict[str, object] | None,
        params: dict[str, object] | None,
        follow_redirects: bool,
    ) -> FakeResponse:
        calls.append((method, url, headers))
        assert timeout == 10.0
        assert json is None
        assert params is None
        assert headers == {"Authorization": "Bearer token-1"}
        assert follow_redirects is True
        return FakeResponse([{"name": "Product"}])

    monkeypatch.setattr(httpx, "request", fake_request)
    products = ApiHealthClient().list_products("token-1")

    assert products == [{"name": "Product"}]
    assert calls[0][0] == "GET"
    assert calls[0][1].endswith("/api/v1/catalog/products")


def test_api_client_permanently_deletes_product(monkeypatch) -> None:
    calls: list[tuple[str, str, dict[str, str]]] = []

    def fake_request(
        method: str,
        url: str,
        timeout: float,
        headers: dict[str, str],
        json: dict[str, object] | None,
        params: dict[str, object] | None,
        follow_redirects: bool,
    ) -> FakeResponse:
        calls.append((method, url, headers))
        assert timeout == 10.0
        assert json is None
        assert params is None
        assert headers == {"Authorization": "Bearer token-1"}
        assert follow_redirects is True
        return FakeResponse({"ok": True})

    monkeypatch.setattr(httpx, "request", fake_request)
    result = ApiHealthClient().permanently_delete_product("token-1", "product-1")

    assert result == {"ok": True}
    assert calls == [
        (
            "DELETE",
            "http://127.0.0.1:8000/api/v1/catalog/products/product-1/permanent",
            {"Authorization": "Bearer token-1"},
        )
    ]


def test_api_client_uploads_product_video(tmp_path, monkeypatch) -> None:
    video_path = tmp_path / "demo.mp4"
    video_path.write_bytes(b"video")
    calls: list[tuple[str, dict[str, str], float, str]] = []

    def fake_post(
        url: str,
        *,
        headers: dict[str, str],
        files: dict[str, tuple[str, object, str]],
        timeout: float,
        follow_redirects: bool,
    ) -> FakeResponse:
        filename, handle, content_type = files["file"]
        assert handle.read() == b"video"
        calls.append((url, headers, timeout, content_type))
        assert filename == str(video_path)
        assert follow_redirects is True
        return FakeResponse({"id": "video-1", "url": "/media/products/demo.mp4"}, 201)

    monkeypatch.setattr(httpx, "post", fake_post)
    result = ApiHealthClient().upload_product_video("token-1", "product-1", str(video_path))

    assert result["id"] == "video-1"
    assert calls == [
        (
            "http://127.0.0.1:8000/api/v1/catalog/products/product-1/videos/upload",
            {"Authorization": "Bearer token-1"},
            180.0,
            "video/mp4",
        )
    ]


def test_api_client_dashboard_summary(monkeypatch) -> None:
    def fake_request(
        method: str,
        url: str,
        timeout: float,
        headers: dict[str, str],
        json: dict[str, object] | None,
        params: dict[str, object] | None,
        follow_redirects: bool,
    ) -> FakeResponse:
        assert method == "GET"
        assert url.endswith("/api/v1/reports/dashboard-summary")
        assert headers == {"Authorization": "Bearer token-1"}
        assert follow_redirects is True
        return FakeResponse({"product_count": 2, "customer_count": 1})

    monkeypatch.setattr(httpx, "request", fake_request)
    summary = ApiHealthClient().get_dashboard_summary("token-1")

    assert summary == {"product_count": 2, "customer_count": 1}


def test_api_client_login_uses_longer_timeout(monkeypatch) -> None:
    calls: list[tuple[str, str, float, dict[str, object] | None]] = []

    def fake_request(
        method: str,
        url: str,
        timeout: float,
        headers: dict[str, str],
        json: dict[str, object] | None,
        params: dict[str, object] | None,
        follow_redirects: bool,
    ) -> FakeResponse:
        calls.append((method, url, timeout, json))
        assert headers == {}
        assert params is None
        assert follow_redirects is True
        return FakeResponse({"access_token": "token-1"})

    monkeypatch.setattr(httpx, "request", fake_request)
    payload = ApiHealthClient().login("admin", "admin12345")

    assert payload == {"access_token": "token-1"}
    assert isinstance(calls[0][3], dict)
    assert isinstance(calls[0][3].get("login_device_id"), str)
    calls[0][3].pop("login_device_id")
    assert calls == [
        (
            "POST",
                "http://127.0.0.1:8000/api/v1/auth/login",
                15.0,
                {
                    "username": "admin",
                    "password": "admin12345",
                    "supports_refresh": True,
                },
            )
        ]


def test_api_client_woocommerce_methods_use_expected_paths(monkeypatch) -> None:
    calls: list[tuple[str, str, float, dict[str, object] | None]] = []

    def fake_request(
        method: str,
        url: str,
        timeout: float,
        headers: dict[str, str],
        json: dict[str, object] | None,
        params: dict[str, object] | None,
        follow_redirects: bool,
    ) -> FakeResponse:
        calls.append((method, url, timeout, json))
        assert params is None
        assert headers == {"Authorization": "Bearer token-1"}
        assert follow_redirects is True
        if url.endswith("/api/v1/woocommerce/sync-runs"):
            return FakeResponse([{"status": "success"}])
        if url.endswith("/api/v1/woocommerce/conflicts"):
            return FakeResponse([{"status": "open"}])
        return FakeResponse({"ok": True})

    monkeypatch.setattr(httpx, "request", fake_request)
    client = ApiHealthClient()

    client.get_woocommerce_config("token-1")
    client.save_woocommerce_config(
        "token-1",
        site_url="https://shop.example.test",
        consumer_key="ck_12345678",
        consumer_secret="cs_12345678",
        webhook_secret="webhook-secret-123456",
        wordpress_username="choiceoye",
        wordpress_application_password="wp-app-pass-123456",
    )
    client.test_woocommerce_connection("token-1")
    client.run_woocommerce_sync("token-1")
    assert client.list_woocommerce_sync_runs("token-1") == [{"status": "success"}]
    assert client.list_woocommerce_conflicts("token-1") == [{"status": "open"}]

    assert [(method, url.rsplit("/api/v1", maxsplit=1)[-1]) for method, url, _t, _j in calls] == [
        ("GET", "/woocommerce/config"),
        ("PUT", "/woocommerce/config"),
        ("POST", "/woocommerce/test-connection"),
        ("POST", "/woocommerce/sync"),
        ("GET", "/woocommerce/sync-runs"),
        ("GET", "/woocommerce/conflicts"),
    ]
    assert calls[1][2] == 10.0
    assert calls[1][3] == {
        "site_url": "https://shop.example.test",
        "consumer_key": "ck_12345678",
        "consumer_secret": "cs_12345678",
        "webhook_secret": "webhook-secret-123456",
        "wordpress_username": "choiceoye",
        "wordpress_application_password": "wp-app-pass-123456",
    }
    assert calls[3][2] == 10.0


def test_api_client_admin_methods_use_expected_paths(monkeypatch) -> None:
    calls: list[tuple[str, str, dict[str, object] | None]] = []

    def fake_request(
        method: str,
        url: str,
        timeout: float,
        headers: dict[str, str],
        json: dict[str, object] | None,
        params: dict[str, object] | None,
        follow_redirects: bool,
    ) -> FakeResponse:
        calls.append((method, url, json))
        assert timeout == 10.0
        assert params is None
        assert headers == {"Authorization": "Bearer token-1"}
        assert follow_redirects is True
        if url.endswith("/api/v1/support/diagnostics"):
            return FakeResponse({"app_version": "0.1.0"})
        return FakeResponse({"ok": True})

    monkeypatch.setattr(httpx, "request", fake_request)
    client = ApiHealthClient()

    client.update_company("token-1", "company-1", {"name": "Updated"})
    client.create_user("token-1", {"username": "cashier", "password": "cashier12345"})
    client.update_user("token-1", "user-1", {"account_status": "paused"})
    client.reset_user_password("token-1", "user-1", "new-password")
    client.create_role("token-1", {"name": "Cashier", "permissions": ["orders.view"]})
    client.activate_license("token-1", license_key="license-12345", plan="standard")
    client.validate_license("token-1")
    client.revoke_license("token-1", "test")
    diagnostics = client.get_diagnostics_summary("token-1")

    assert diagnostics == {"app_version": "0.1.0"}
    assert [call[0] for call in calls] == [
        "PATCH",
        "POST",
        "PATCH",
        "POST",
        "POST",
        "POST",
        "POST",
        "POST",
        "GET",
    ]
    assert calls[0][1].endswith("/api/v1/tenancy/companies/company-1")
    assert calls[-1][1].endswith("/api/v1/support/diagnostics")


def test_api_client_ledger_workspace_methods_use_scoped_paths_and_filters(
    monkeypatch,
) -> None:
    calls: list[tuple[str, str, dict[str, object] | None]] = []

    def fake_request(
        method: str,
        url: str,
        timeout: float,
        headers: dict[str, str],
        json: dict[str, object] | None = None,
        params: dict[str, object] | None = None,
        follow_redirects: bool = False,
    ) -> FakeResponse:
        calls.append((method, url, params))
        assert timeout == 10.0
        assert headers == {"Authorization": "Bearer token-1"}
        assert json is None
        assert follow_redirects is True
        if url.endswith("/api/v1/ledger/export/journals.csv"):
            return FakeResponse({}, text="entry_number,status\nJE-1,posted\n")
        return FakeResponse([])

    monkeypatch.setattr(httpx, "request", fake_request)
    client = ApiHealthClient()

    client.list_ledger_journals(
        "token-1",
        "vendor-1",
        account_id="account-1",
        source_type="payment",
        status="posted",
        date_from="2026-01-01T00:00:00Z",
        date_to="2026-01-31T23:59:59Z",
    )
    client.list_vendor_users_for_admin("token-1", "vendor-1")
    client.list_vendor_audit_for_admin("token-1", "vendor-1")
    exported = client.export_ledger_journals_csv(
        "token-1", vendor_id="vendor-1", status="posted"
    )

    assert exported.startswith("entry_number,status")
    assert calls[0][1].endswith("/api/v1/ledger/journals")
    assert calls[0][2] == {
        "vendor_id": "vendor-1",
        "account_id": "account-1",
        "source_type": "payment",
        "status": "posted",
        "date_from": "2026-01-01T00:00:00Z",
        "date_to": "2026-01-31T23:59:59Z",
    }
    assert calls[1][1].endswith("/api/v1/marketplace/vendors/vendor-1/users")
    assert calls[2][1].endswith("/api/v1/ledger/vendors/vendor-1/audit")
    assert calls[3][1].endswith("/api/v1/ledger/export/journals.csv")
    assert calls[3][2] == {"vendor_id": "vendor-1", "status": "posted"}


def test_api_client_catalog_create_methods_and_code_suggestion(monkeypatch) -> None:
    calls: list[tuple[str, str, dict[str, object] | None]] = []

    def fake_request(
        method: str,
        url: str,
        timeout: float,
        headers: dict[str, str],
        json: dict[str, object] | None,
        params: dict[str, object] | None,
        follow_redirects: bool,
    ) -> FakeResponse:
        calls.append((method, url, json))
        assert timeout == 10.0
        assert params is None
        assert headers == {"Authorization": "Bearer token-1"}
        assert follow_redirects is True
        if url.endswith("/api/v1/catalog/products/code-suggestion"):
            return FakeResponse({"sku": "CO-000001", "barcode": "2000000000012"})
        return FakeResponse({"ok": True})

    monkeypatch.setattr(httpx, "request", fake_request)
    client = ApiHealthClient()

    category = client.create_category("token-1", {"name": "Cases"})
    brand = client.create_brand("token-1", {"name": "Choice"})
    suggestion = client.get_product_code_suggestion("token-1")

    assert category == {"ok": True}
    assert brand == {"ok": True}
    assert suggestion == {"sku": "CO-000001", "barcode": "2000000000012"}
    assert [call[0] for call in calls] == ["POST", "POST", "GET"]
    assert calls[0][1].endswith("/api/v1/catalog/categories")
    assert calls[1][1].endswith("/api/v1/catalog/brands")
    assert calls[2][1].endswith("/api/v1/catalog/products/code-suggestion")


def test_format_api_error_classifies_offline_and_migration_errors() -> None:
    offline = ApiResponseError(0, "Unable to connect to http://127.0.0.1:8000: connection refused")
    timeout = ApiResponseError(0, "Unable to connect to http://127.0.0.1:8000: timed out")
    schema_error = ApiResponseError(
        500,
        "(sqlite3.OperationalError) no such column: sync_run_logs.company_id",
    )

    assert "Start RUN_ERP.bat local" in desktop_main.format_api_error(offline, "http://127.0.0.1:8000")
    assert "did not complete this request" in desktop_main.format_api_error(
        timeout,
        "http://127.0.0.1:8000",
    )
    assert "STOP_ERP.bat" in desktop_main.format_api_error(timeout, "http://127.0.0.1:8000")
    assert "database schema is out of date" in desktop_main.format_api_error(
        schema_error,
        "http://127.0.0.1:8000",
    )


def test_api_offline_message_detection_is_specific() -> None:
    assert desktop_main.is_api_offline_message(
        "API is offline at http://127.0.0.1:8000. Start RUN_ERP.bat local."
    )
    assert not desktop_main.is_api_offline_message("WooCommerce sync failed: unauthorized")
    assert not desktop_main.is_api_offline_message("API online: healthy.")


def test_api_client_retries_safe_reads_after_a_transient_timeout(monkeypatch) -> None:
    calls: list[float] = []

    def fake_request(
        method: str,
        url: str,
        timeout: float,
        headers: dict[str, str],
        json: dict[str, object] | None,
        params: dict[str, object] | None,
        follow_redirects: bool,
    ) -> FakeResponse:
        calls.append(timeout)
        assert method == "GET"
        assert url.endswith("/api/v1/catalog/products")
        assert headers == {"Authorization": "Bearer token-1"}
        assert json is None
        assert params is None
        assert follow_redirects is True
        if len(calls) == 1:
            raise httpx.ReadTimeout("temporary busy")
        return FakeResponse([{"name": "Product"}])

    monkeypatch.setattr(httpx, "request", fake_request)
    monkeypatch.setattr("erp.apps.desktop.api_client.time.sleep", lambda _: None)

    assert ApiHealthClient().list_products("token-1") == [{"name": "Product"}]
    assert calls == [10.0, 10.0]


def test_recovered_api_page_message_is_available_for_every_page() -> None:
    for page_name in desktop_main.navigation_items():
        assert (
            desktop_main.recovered_api_page_message(
                "API is offline at http://127.0.0.1:8000. Start RUN_ERP.bat local.",
                page_name,
            )
            == f"API online. {page_name} is ready."
        )

    assert (
        desktop_main.recovered_api_page_message(
            "WooCommerce sync failed: unauthorized",
            "WooCommerce",
        )
        is None
    )


def test_api_client_parses_json_error_detail(monkeypatch) -> None:
    def fake_request(
        method: str,
        url: str,
        timeout: float,
        headers: dict[str, str],
        json: dict[str, object] | None,
        params: dict[str, object] | None,
        follow_redirects: bool,
    ) -> httpx.Response:
        request = httpx.Request(method, url)
        return httpx.Response(
            404,
            json={"detail": {"remote_status": 404}, "message": "Not found"},
            request=request,
        )

    monkeypatch.setattr(httpx, "request", fake_request)
    client = ApiHealthClient()

    try:
        client.request("POST", "/api/v1/woocommerce/sync", token="token-1")
    except ApiResponseError as exc:
        assert exc.status_code == 404
        assert "remote_status" in str(exc)
        assert "Not found" in str(exc)
        assert exc.url.endswith("/api/v1/woocommerce/sync")
    else:  # pragma: no cover - defensive
        raise AssertionError("ApiResponseError was not raised")
