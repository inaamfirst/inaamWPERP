from __future__ import annotations

import threading
from pathlib import Path

import httpx
import pytest

from erp.apps.desktop import api_client as api_client_module
from erp.apps.desktop import main as desktop_main
from erp.apps.desktop.api_client import (
    ApiHealthClient,
    ApiResponseError,
    CredentialStorageError,
)
from erp.apps.desktop.auth import (
    ACCOUNT_STATUSES,
    DESKTOP_PREFERENCE_KEYS,
    VENDOR_ONBOARDING_OPTIONS,
    VENDOR_STATUSES,
    build_vendor_account_payload,
    navigation_visibility,
    public_auth_url,
    role_names_for_session,
    session_display_lines,
    should_load_vendor_self,
    vendor_onboarding_result_lines,
)


class PasswordDeleteError(Exception):
    pass


class FakeBackend:
    priority = 5


class FakeKeyring:
    def __init__(self) -> None:
        self.values: dict[tuple[str, str], str] = {}
        self.writes: list[tuple[str, str, str]] = []
        self.deletes: list[tuple[str, str]] = []
        self.fail_save = False
        self.fail_read = False
        self.fail_delete = False
        self._lock = threading.Lock()

    def get_keyring(self) -> FakeBackend:
        return FakeBackend()

    def set_password(self, service: str, account: str, value: str) -> None:
        if self.fail_save:
            raise RuntimeError("vault write failed")
        with self._lock:
            self.values[(service, account)] = value
            self.writes.append((service, account, value))

    def get_password(self, service: str, account: str) -> str | None:
        if self.fail_read:
            raise RuntimeError("vault read failed")
        with self._lock:
            return self.values.get((service, account))

    def delete_password(self, service: str, account: str) -> None:
        if self.fail_delete:
            raise RuntimeError("vault delete failed")
        with self._lock:
            self.deletes.append((service, account))
            if (service, account) not in self.values:
                raise PasswordDeleteError()
            del self.values[(service, account)]


class FakeResponse:
    def __init__(self, url: str, payload: object, status_code: int = 200) -> None:
        self.status_code = status_code
        self._payload = payload
        self.text = ""
        self.content = b"response"
        self.request = httpx.Request("GET", url)

    def json(self) -> object:
        return self._payload


@pytest.fixture()
def vault(monkeypatch: pytest.MonkeyPatch) -> FakeKeyring:
    fake = FakeKeyring()
    monkeypatch.setattr(api_client_module, "keyring", fake)
    return fake


def auth_payload(
    access: str = "access-new",
    refresh: str | None = "refresh-new",
) -> dict[str, object]:
    return {
        "access_token": access,
        "refresh_token": refresh,
        "expires_at": "2026-07-29T12:15:00Z",
        "refresh_expires_at": "2026-08-28T12:00:00Z",
        "session_id": "session-1",
        "permissions": ["catalog.view"],
        "user": {"username": "admin"},
    }


def test_only_refresh_token_enters_keyring_and_session_display_redacts_secrets(
    vault: FakeKeyring,
) -> None:
    client = ApiHealthClient("https://erp.example.test")
    payload = auth_payload(access="access-secret", refresh="refresh-secret")

    credentials = client.install_session(payload, remembered=True)

    assert credentials.access_token == "access-secret"
    assert client.access_token == "access-secret"
    assert vault.writes == [
        (client._credential_service, "refresh_token", "refresh-secret")  # noqa: SLF001
    ]
    assert "access-secret" not in repr(vault.values)
    assert DESKTOP_PREFERENCE_KEYS == {
        "username": "authentication/username",
        "workspace": "authentication/workspace",
    }
    lines = session_display_lines(
        payload,
        {
            "user": {"username": "admin", "must_change_password": False},
            "company": {"name": "ChoiceOye", "slug": "choiceoye"},
            "session_created_at": "2026-07-29T12:00:00Z",
        },
        remembered=True,
        roles=["Administrator"],
    )
    rendered = "\n".join(lines)
    assert "access-secret" not in rendered
    assert "refresh-secret" not in rendered
    assert "Password change required: no" in rendered


def test_password_and_tokens_are_not_persisted_in_desktop_preferences_or_source() -> None:
    source = Path("erp/apps/desktop/main.py").read_text(encoding="utf-8")
    settings_writes = [line for line in source.splitlines() if "preferences.setValue" in line]

    assert set(DESKTOP_PREFERENCE_KEYS) == {"username", "workspace"}
    assert all("password" not in line.lower() for line in settings_writes)
    assert all("token" not in line.lower() for line in settings_writes)
    assert "QSettings" not in Path("erp/apps/desktop/api_client.py").read_text(encoding="utf-8")


def test_desktop_authentication_and_admin_widgets_build_offscreen(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from PySide6.QtWidgets import QApplication

    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    monkeypatch.setattr(ApiHealthClient, "secure_storage_available", lambda _self: False)
    monkeypatch.setattr(QApplication, "exec", lambda _self: 0)

    assert desktop_main.run() == 0


def test_keyring_unavailable_disables_secure_storage(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(api_client_module, "keyring", None)
    client = ApiHealthClient()
    monkeypatch.setattr(client, "_best_effort_revoke", lambda *_args: None)

    assert client.secure_storage_available() is False
    with pytest.raises(CredentialStorageError):
        client.install_session(auth_payload(), remembered=True)
    assert client.access_token is None


def test_keyring_save_failure_revokes_new_server_session(
    vault: FakeKeyring,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = ApiHealthClient()
    vault.fail_save = True
    revoked: list[tuple[str | None, str | None]] = []

    def fake_logout(
        token: str | None = None,
        *,
        refresh_token: str | None = None,
        all_sessions: bool = False,
    ) -> None:
        assert all_sessions is False
        revoked.append((token, refresh_token))

    monkeypatch.setattr(client, "logout", fake_logout)

    with pytest.raises(CredentialStorageError):
        client.install_session(
            auth_payload(access="new-access", refresh="new-refresh"),
            remembered=True,
        )

    assert revoked == [("new-access", "new-refresh")]
    assert client.access_token is None
    assert client.refresh_token is None


def test_startup_restore_rotates_and_replaces_saved_token(
    vault: FakeKeyring,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = ApiHealthClient()
    vault.values[(client._credential_service, "refresh_token")] = "refresh-old"  # noqa: SLF001
    calls: list[dict[str, object] | None] = []

    def fake_request(
        method: str,
        url: str,
        timeout: float,
        headers: dict[str, str],
        json: dict[str, object] | None,
        params: dict[str, object] | None,
        follow_redirects: bool,
    ) -> FakeResponse:
        calls.append(json)
        assert method == "POST"
        return FakeResponse(url, auth_payload(access="access-restored", refresh="refresh-rotated"))

    monkeypatch.setattr(httpx, "request", fake_request)

    payload = client.restore_saved_session()

    assert payload is not None
    assert calls == [{"refresh_token": "refresh-old"}]
    assert client.access_token == "access-restored"
    assert client.refresh_token == "refresh-rotated"
    assert vault.values[(client._credential_service, "refresh_token")] == "refresh-rotated"  # noqa: SLF001


def test_nonremembered_login_clears_an_older_remembered_account(vault: FakeKeyring) -> None:
    client = ApiHealthClient()
    key = (client._credential_service, "refresh_token")  # noqa: SLF001
    vault.values[key] = "account-a-refresh"

    client.install_session(
        auth_payload(access="account-b-access", refresh="account-b-refresh"),
        remembered=False,
    )

    assert key not in vault.values
    assert client.access_token == "account-b-access"
    assert client.remembered is False


def test_logout_uses_refresh_only_and_always_clears_local_state(
    vault: FakeKeyring,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = ApiHealthClient()
    client.install_session(auth_payload(), remembered=True)
    with client._session_lock:  # noqa: SLF001
        client._access_token = None  # noqa: SLF001
    calls: list[tuple[dict[str, str], dict[str, object] | None]] = []

    def fake_request(
        method: str,
        url: str,
        timeout: float,
        headers: dict[str, str],
        json: dict[str, object] | None,
        params: dict[str, object] | None,
        follow_redirects: bool,
    ) -> FakeResponse:
        calls.append((headers, json))
        return FakeResponse(url, {"ok": True})

    monkeypatch.setattr(httpx, "request", fake_request)

    result = client.logout_current_session()
    repeated = client.logout_current_session()

    assert result.server_confirmed is True
    assert repeated.server_confirmed is True
    assert calls == [({}, {"all_sessions": False, "refresh_token": "refresh-new"})]
    assert client.access_token is None
    assert client.refresh_token is None
    assert not vault.values


def test_request_refreshes_once_and_retries_original_once(
    vault: FakeKeyring,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = ApiHealthClient()
    client.install_session(
        auth_payload(access="access-old", refresh="refresh-old"),
        remembered=True,
    )
    calls: list[tuple[str, str | None]] = []

    def fake_request(
        method: str,
        url: str,
        timeout: float,
        headers: dict[str, str],
        json: dict[str, object] | None,
        params: dict[str, object] | None,
        follow_redirects: bool,
    ) -> FakeResponse:
        authorization = headers.get("Authorization")
        calls.append((url.rsplit("/", 1)[-1], authorization))
        if url.endswith("/api/v1/auth/refresh"):
            return FakeResponse(url, auth_payload(access="access-new", refresh="refresh-new"))
        if authorization == "Bearer access-old":
            return FakeResponse(url, {"detail": "expired"}, status_code=401)
        return FakeResponse(url, {"ok": True})

    monkeypatch.setattr(httpx, "request", fake_request)

    response = client.request("POST", "/api/v1/example", token="access-old", json={"x": 1})

    assert response == {"ok": True}
    assert calls == [
        ("example", "Bearer access-old"),
        ("refresh", None),
        ("example", "Bearer access-new"),
    ]
    assert vault.values[(client._credential_service, "refresh_token")] == "refresh-new"  # noqa: SLF001


def test_concurrent_requests_share_one_refresh_result(
    vault: FakeKeyring,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = ApiHealthClient()
    client.install_session(
        auth_payload(access="access-old", refresh="refresh-old"),
        remembered=True,
    )
    old_request_barrier = threading.Barrier(2)
    count_lock = threading.Lock()
    refresh_count = 0

    def fake_request(
        method: str,
        url: str,
        timeout: float,
        headers: dict[str, str],
        json: dict[str, object] | None,
        params: dict[str, object] | None,
        follow_redirects: bool,
    ) -> FakeResponse:
        nonlocal refresh_count
        if url.endswith("/api/v1/auth/refresh"):
            with count_lock:
                refresh_count += 1
            return FakeResponse(url, auth_payload(access="access-new", refresh="refresh-new"))
        if headers.get("Authorization") == "Bearer access-old":
            old_request_barrier.wait(timeout=5)
            return FakeResponse(url, {"detail": "expired"}, status_code=401)
        return FakeResponse(url, {"ok": True})

    monkeypatch.setattr(httpx, "request", fake_request)
    results: list[object] = []
    errors: list[BaseException] = []

    def worker() -> None:
        try:
            results.append(client.request("GET", "/api/v1/example", token="access-old"))
        except BaseException as exc:  # pragma: no cover - asserted empty below
            errors.append(exc)

    threads = [threading.Thread(target=worker), threading.Thread(target=worker)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)

    assert errors == []
    assert results == [{"ok": True}, {"ok": True}]
    assert refresh_count == 1


def test_403_does_not_refresh_and_failed_refresh_clears_session(
    vault: FakeKeyring,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = ApiHealthClient()
    client.install_session(
        auth_payload(access="access-old", refresh="refresh-old"),
        remembered=True,
    )
    refresh_calls = 0

    def forbidden_request(
        method: str,
        url: str,
        timeout: float,
        headers: dict[str, str],
        json: dict[str, object] | None,
        params: dict[str, object] | None,
        follow_redirects: bool,
    ) -> FakeResponse:
        nonlocal refresh_calls
        if url.endswith("/api/v1/auth/refresh"):
            refresh_calls += 1
        return FakeResponse(url, {"detail": "Missing required permission"}, status_code=403)

    monkeypatch.setattr(httpx, "request", forbidden_request)
    with pytest.raises(ApiResponseError) as forbidden:
        client.request("GET", "/api/v1/admin", token="access-old")
    assert forbidden.value.status_code == 403
    assert refresh_calls == 0
    assert client.access_token == "access-old"

    def expired_request(
        method: str,
        url: str,
        timeout: float,
        headers: dict[str, str],
        json: dict[str, object] | None,
        params: dict[str, object] | None,
        follow_redirects: bool,
    ) -> FakeResponse:
        return FakeResponse(url, {"detail": "expired"}, status_code=401)

    monkeypatch.setattr(httpx, "request", expired_request)
    with pytest.raises(ApiResponseError):
        client.request("GET", "/api/v1/example", token="access-old")
    assert client.access_token is None
    assert client.refresh_token is None
    assert not vault.values


def test_legacy_nonrefresh_session_is_not_put_in_a_retry_loop(
    vault: FakeKeyring,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = ApiHealthClient()
    client.install_session(auth_payload(access="legacy-access", refresh=None), remembered=False)
    calls = 0

    def fake_request(
        method: str,
        url: str,
        timeout: float,
        headers: dict[str, str],
        json: dict[str, object] | None,
        params: dict[str, object] | None,
        follow_redirects: bool,
    ) -> FakeResponse:
        nonlocal calls
        calls += 1
        return FakeResponse(url, {"detail": "expired"}, status_code=401)

    monkeypatch.setattr(httpx, "request", fake_request)
    with pytest.raises(ApiResponseError):
        client.request("GET", "/api/v1/example", token="legacy-access")
    assert calls == 1
    assert client.access_token is None


def test_navigation_status_onboarding_and_public_links_are_role_safe() -> None:
    vendor_navigation = navigation_visibility(
        [
            "vendor.profile.view",
            "vendor.products.view",
            "vendor.orders.view",
            "vendor.settlements.view",
        ]
    )
    assert vendor_navigation["Marketplace"] is True
    assert vendor_navigation["Dashboard"] is True
    assert vendor_navigation["Admin"] is False
    assert vendor_navigation["Accounting"] is False
    assert vendor_navigation["Products"] is False
    assert role_names_for_session(
        {"user": {"role_names": ["Administrator", "Vendor"]}},
        ["vendor.profile.view", "identity.manage_users"],
    ) == ["Administrator", "Vendor"]
    assert role_names_for_session(
        {"user": {}},
        ["vendor.profile.view", "vendor.orders.view"],
    ) == ["Vendor"]
    assert should_load_vendor_self(
        ["Vendor"], {"vendor.profile.view", "vendor.orders.view"}
    )
    assert not should_load_vendor_self(
        ["Administrator", "Vendor"], {"vendor.profile.view", "vendors.manage"}
    )
    restricted = navigation_visibility(["identity.manage_users"], must_change_password=True)
    assert not any(restricted.values())
    assert ACCOUNT_STATUSES == ("active", "pending", "paused", "stopped")
    assert VENDOR_STATUSES == ACCOUNT_STATUSES
    assert VENDOR_ONBOARDING_OPTIONS == (
        ("Activation email", "activation"),
        ("Temporary password", "temporary_password"),
    )
    assert public_auth_url("https://erp.example.test/api/v1", "/register", "shop one") == (
        "https://erp.example.test/register?workspace=shop+one"
    )
    assert public_auth_url(
        "https://erp.example.test", "/forgot-password", "choiceoye"
    ) == "https://erp.example.test/forgot-password?workspace=choiceoye"
    with pytest.raises(ValueError):
        public_auth_url("file:///tmp/erp", "/register", "choiceoye")


def test_vendor_temporary_password_payload_and_result_never_reveal_credentials() -> None:
    temporary = build_vendor_account_payload(
        business_name="Vendor One",
        username="vendor-one",
        email="vendor@example.test",
        contact_name="Vendor Owner",
        phone=None,
        onboarding="temporary_password",
        temporary_password="temporary-password",
        default_commission_bps=500,
    )
    activation = build_vendor_account_payload(
        business_name="Vendor Two",
        username="vendor-two",
        email="vendor2@example.test",
        contact_name=None,
        phone=None,
        onboarding="activation",
        temporary_password=None,
        default_commission_bps=0,
    )

    assert temporary["password"] == "temporary-password"
    assert temporary["use_activation"] is False
    assert "password" not in activation
    assert activation["use_activation"] is True
    result_lines = vendor_onboarding_result_lines(
        {
            "vendor": {"name": "Vendor One", "access_status": "active"},
            "user": {
                "id": "user-1",
                "username": "vendor-one",
                "account_status": "active",
                "must_change_password": True,
            },
            "onboarding_method": "temporary_password",
            "activation_delivery": "not_requested",
            "activation_token": "must-not-render",
        }
    )
    rendered = "\n".join(result_lines)
    assert "temporary-password" not in rendered
    assert "must-not-render" not in rendered
    assert "Password change required: yes" in rendered


def test_vendor_lifecycle_client_uses_phase3_endpoints(
    vault: FakeKeyring,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del vault
    client = ApiHealthClient()
    calls: list[tuple[str, dict[str, object] | None]] = []

    def fake_request(
        method: str,
        url: str,
        timeout: float,
        headers: dict[str, str],
        json: dict[str, object] | None,
        params: dict[str, object] | None,
        follow_redirects: bool,
    ) -> FakeResponse:
        calls.append((url, json))
        return FakeResponse(url, {"access_status": "active"})

    monkeypatch.setattr(httpx, "request", fake_request)
    client.approve_vendor("access", "vendor-1")
    client.pause_vendor("access", "vendor-1", "review")
    client.reactivate_vendor("access", "vendor-1", "approved")
    client.stop_vendor("access", "vendor-1", "closed")

    assert [url.rsplit("/", 1)[-1] for url, _payload in calls] == [
        "approve",
        "pause",
        "reactivate",
        "stop",
    ]
    assert calls[1][1] == {"reason": "review"}
