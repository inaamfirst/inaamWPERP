from __future__ import annotations

import hashlib
import json as jsonlib
import threading
import time
import uuid
from dataclasses import dataclass

import httpx

try:  # The packaged desktop includes keyring; tests/minimal API installs may not.
    import keyring
except ImportError:  # pragma: no cover - exercised only by minimal installations
    keyring = None  # type: ignore[assignment]


@dataclass(frozen=True)
class ApiStatus:
    reachable: bool
    status: str
    detail: str
    module_count: int = 0


class ApiResponseError(RuntimeError):
    def __init__(self, status_code: int, detail: str, *, url: str | None = None) -> None:
        self.status_code = status_code
        self.detail = detail
        self.url = url
        location = f" for {url}" if url else ""
        super().__init__(f"API request failed with HTTP {status_code}{location}: {detail}")


class CredentialStorageError(RuntimeError):
    """Raised when the operating-system credential vault cannot be used safely."""


@dataclass(frozen=True)
class SessionCredentials:
    access_token: str | None
    refresh_token: str | None
    remembered: bool
    generation: int


@dataclass(frozen=True)
class LogoutResult:
    server_confirmed: bool
    credential_cleared: bool
    warning: str | None = None


class ApiHealthClient:
    """Small synchronous client used by the desktop application.

    The desktop talks to a local API which can briefly be busy committing a
    WooCommerce batch.  A two-second limit was too aggressive for normal
    catalog reads, so regular requests get a practical timeout while health
    probes remain short and non-disruptive.
    """

    def __init__(
        self,
        base_url: str = "http://127.0.0.1:8000",
        timeout: float = 10.0,
        health_timeout: float = 2.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.health_timeout = health_timeout
        self._credential_service = (
            "enterprise-commerce-erp:"
            + hashlib.sha256(self.base_url.encode("utf-8")).hexdigest()[:16]
        )
        self._login_device_id = self._load_login_device_id()
        self._session_lock = threading.RLock()
        self._refresh_lock = threading.Lock()
        self._access_token: str | None = None
        self._refresh_token: str | None = None
        self._remembered = False
        self._session_generation = 0

    def _load_login_device_id(self) -> str:
        """Load one install identifier without making login depend on keyring."""

        if keyring is not None:
            try:
                existing = keyring.get_password(self._credential_service, "login_device_id")
                if existing:
                    return existing
                generated = str(uuid.uuid4())
                keyring.set_password(self._credential_service, "login_device_id", generated)
                return generated
            except Exception:
                pass
        return str(uuid.uuid4())

    @property
    def access_token(self) -> str | None:
        with self._session_lock:
            return self._access_token

    @property
    def refresh_token(self) -> str | None:
        with self._session_lock:
            return self._refresh_token

    @property
    def remembered(self) -> bool:
        with self._session_lock:
            return self._remembered

    @property
    def session_generation(self) -> int:
        with self._session_lock:
            return self._session_generation

    def session_credentials(self) -> SessionCredentials:
        with self._session_lock:
            return SessionCredentials(
                access_token=self._access_token,
                refresh_token=self._refresh_token,
                remembered=self._remembered,
                generation=self._session_generation,
            )

    def secure_storage_available(self) -> bool:
        if keyring is None:
            return False
        try:
            backend = keyring.get_keyring()
            return float(getattr(backend, "priority", 0)) > 0
        except Exception:
            return False

    def get_health(self) -> ApiStatus:
        try:
            payload = self.request("GET", "/api/v1/health", timeout=self.health_timeout)
            if not isinstance(payload, dict):
                raise ApiResponseError(500, "Health endpoint returned a non-object payload.")
            return ApiStatus(
                reachable=True,
                status=str(payload.get("status", "unknown")),
                detail=str(payload.get("app_name", "ERP API")),
                module_count=int(payload.get("module_count", 0)),
            )
        except ApiResponseError as exc:
            return ApiStatus(
                reachable=False,
                status="offline",
                detail=f"API is unreachable: {exc}",
            )
        except Exception as exc:
            return ApiStatus(
                reachable=False,
                status="offline",
                detail=f"API is unreachable: {exc}",
            )

    def get_modules(self) -> list[dict[str, object]]:
        try:
            payload = self.request("GET", "/api/v1/modules")
            if isinstance(payload, dict):
                modules = payload.get("modules", [])
                return modules if isinstance(modules, list) else []
            return []
        except ApiResponseError:
            return []

    def _headers(self, token: str | None = None) -> dict[str, str]:
        if not token:
            return {}
        return {"Authorization": f"Bearer {token}"}

    def request(
        self,
        method: str,
        path: str,
        *,
        token: str | None = None,
        json: dict[str, object] | None = None,
        params: dict[str, object] | None = None,
        timeout: float | None = None,
        allow_auth_refresh: bool = True,
    ) -> dict[str, object] | list[dict[str, object]]:
        try:
            return self._request_once(
                method,
                path,
                token=token,
                json=json,
                params=params,
                timeout=timeout,
            )
        except ApiResponseError as exc:
            if exc.status_code == 403 and self._is_session_ineligible_error(exc.detail):
                self._discard_local_session()
            if (
                exc.status_code != 401
                or not token
                or not allow_auth_refresh
                or path
                in {
                    "/api/v1/auth/login",
                    "/api/v1/auth/refresh",
                    "/api/v1/auth/logout",
                }
            ):
                raise
            replacement = self._refresh_after_unauthorized(token)
            if not replacement:
                raise
            try:
                return self._request_once(
                    method,
                    path,
                    token=replacement,
                    json=json,
                    params=params,
                    timeout=timeout,
                )
            except ApiResponseError as retry_exc:
                if retry_exc.status_code == 401 or (
                    retry_exc.status_code == 403
                    and self._is_session_ineligible_error(retry_exc.detail)
                ):
                    self._discard_local_session()
                raise

    def _request_once(
        self,
        method: str,
        path: str,
        *,
        token: str | None = None,
        json: dict[str, object] | None = None,
        params: dict[str, object] | None = None,
        timeout: float | None = None,
    ) -> dict[str, object] | list[dict[str, object]]:
        request_timeout = timeout or self.timeout
        request_url = f"{self.base_url}{path}"
        # Never replay writes. A single retry for safe reads absorbs a short
        # local SQLite/worker pause without duplicating a user action.
        attempts = 2 if method.upper() in {"GET", "HEAD", "OPTIONS"} else 1
        response: httpx.Response | None = None
        for attempt in range(attempts):
            try:
                response = httpx.request(
                    method,
                    request_url,
                    timeout=request_timeout,
                    headers=self._headers(token),
                    json=json,
                    params=params,
                    follow_redirects=True,
                )
                break
            except httpx.TimeoutException as exc:
                if attempt + 1 < attempts:
                    time.sleep(0.15)
                    continue
                raise ApiResponseError(
                    0,
                    f"Unable to connect to {self.base_url}: request timed out after "
                    f"{request_timeout:g} seconds ({exc})",
                    url=request_url,
                ) from exc
            except httpx.RequestError as exc:
                raise ApiResponseError(
                    0,
                    f"Unable to connect to {self.base_url}: {exc}",
                    url=request_url,
                ) from exc

        if response is None:  # pragma: no cover - defensive guard
            raise ApiResponseError(0, f"Unable to connect to {self.base_url}.", url=request_url)
        if response.status_code >= 400:
            detail: str
            try:
                payload = response.json()
            except Exception:
                payload = None
            if isinstance(payload, dict):
                parts: list[str] = []
                for key in ("detail", "message", "error", "code", "operation", "request_id"):
                    value = payload.get(key)
                    if value is not None and value != "":
                        parts.append(f"{key}={value}")
                detail = (
                    "; ".join(parts)
                    if parts
                    else jsonlib.dumps(payload, ensure_ascii=True, default=str)
                )
            elif isinstance(payload, list):
                detail = jsonlib.dumps(payload[:3], ensure_ascii=True, default=str)
            else:
                detail = (response.text or "").strip() or "No response body."
            raise ApiResponseError(response.status_code, detail, url=str(response.request.url))
        if response.status_code == 204 or not getattr(response, "content", b"response"):
            return {}
        payload = response.json()
        if isinstance(payload, dict | list):
            return payload
        return {}

    @staticmethod
    def _is_session_ineligible_error(detail: str) -> bool:
        lowered = detail.lower()
        return any(
            marker in lowered
            for marker in (
                "account is pending",
                "account is paused",
                "account is stopped",
                "account is inactive",
                "company account is not active",
                "vendor account is pending",
                "vendor account is paused",
                "vendor account is stopped",
                "authenticated user is not active",
            )
        )

    def download_text(
        self,
        path: str,
        *,
        token: str,
        params: dict[str, object] | None = None,
    ) -> str:
        try:
            return self._download_text_once(path, token=token, params=params)
        except ApiResponseError as exc:
            if exc.status_code != 401:
                if exc.status_code == 403 and self._is_session_ineligible_error(exc.detail):
                    self._discard_local_session()
                raise
            replacement = self._refresh_after_unauthorized(token)
            if not replacement:
                raise
            try:
                return self._download_text_once(path, token=replacement, params=params)
            except ApiResponseError as retry_exc:
                if retry_exc.status_code == 401:
                    self._discard_local_session()
                raise

    def _download_text_once(
        self,
        path: str,
        *,
        token: str,
        params: dict[str, object] | None = None,
    ) -> str:
        request_url = f"{self.base_url}{path}"
        try:
            response = httpx.request(
                "GET",
                request_url,
                timeout=self.timeout,
                headers=self._headers(token),
                params=params,
                follow_redirects=True,
            )
        except httpx.RequestError as exc:
            raise ApiResponseError(
                0,
                f"Unable to connect to {self.base_url}: {exc}",
                url=request_url,
            ) from exc
        if response.status_code >= 400:
            raise ApiResponseError(
                response.status_code,
                (response.text or "No response body.").strip(),
                url=str(response.request.url),
            )
        return response.text

    def login(
        self,
        username: str,
        password: str,
        workspace_slug: str | None = None,
        company_id: str | None = None,
        remember_me: bool = False,
    ) -> dict[str, object]:
        payload: dict[str, object] = {
            "username": username,
            "password": password,
            "supports_refresh": True,
            "login_device_id": self._login_device_id,
        }
        if remember_me:
            payload["remember_me"] = True
        if workspace_slug:
            payload["workspace_slug"] = workspace_slug
        if company_id:
            payload["company_id"] = company_id
        response = self.request("POST", "/api/v1/auth/login", json=payload, timeout=15.0)
        return response if isinstance(response, dict) else {}

    def get_current_session(self, token: str) -> dict[str, object]:
        response = self.request("GET", "/api/v1/auth/me", token=token)
        return response if isinstance(response, dict) else {}

    def refresh_session(self, refresh_token: str) -> dict[str, object]:
        response = self.request(
            "POST",
            "/api/v1/auth/refresh",
            json={"refresh_token": refresh_token},
            timeout=15.0,
            allow_auth_refresh=False,
        )
        return response if isinstance(response, dict) else {}

    def logout(
        self,
        token: str | None = None,
        *,
        refresh_token: str | None = None,
        all_sessions: bool = False,
    ) -> None:
        payload: dict[str, object] = {"all_sessions": all_sessions}
        if refresh_token:
            payload["refresh_token"] = refresh_token
        self.request(
            "POST",
            "/api/v1/auth/logout",
            token=token,
            json=payload,
            allow_auth_refresh=False,
        )

    def change_password(
        self,
        token: str,
        *,
        current_password: str,
        new_password: str,
    ) -> None:
        self.request(
            "POST",
            "/api/v1/auth/change-password",
            token=token,
            json={"current_password": current_password, "new_password": new_password},
        )

    def save_refresh_token(self, refresh_token: str) -> None:
        if not refresh_token:
            raise CredentialStorageError("A refresh token is required for remembered login.")
        if not self.secure_storage_available():
            raise CredentialStorageError("Secure OS credential storage is unavailable.")
        try:
            keyring.set_password(self._credential_service, "refresh_token", refresh_token)
        except Exception as exc:
            raise CredentialStorageError(
                "Secure OS credential storage could not save the login."
            ) from exc

    def load_refresh_token(self) -> str | None:
        if not self.secure_storage_available():
            return None
        try:
            value = keyring.get_password(self._credential_service, "refresh_token")
        except Exception as exc:
            raise CredentialStorageError("Secure OS credential storage could not be read.") from exc
        return value if isinstance(value, str) and value else None

    def clear_refresh_token(self) -> None:
        if not self.secure_storage_available():
            return
        try:
            keyring.delete_password(self._credential_service, "refresh_token")
        except Exception as exc:
            if exc.__class__.__name__ == "PasswordDeleteError":
                return
            raise CredentialStorageError(
                "Secure OS credential storage could not remove the saved login."
            ) from exc

    def install_session(
        self,
        payload: dict[str, object],
        *,
        remembered: bool,
    ) -> SessionCredentials:
        access_token = payload.get("access_token")
        refresh_token = payload.get("refresh_token")
        if not isinstance(access_token, str) or not access_token:
            raise ApiResponseError(500, "Authentication response did not include an access token.")
        normalized_refresh = (
            refresh_token if isinstance(refresh_token, str) and refresh_token else None
        )
        try:
            if remembered:
                if not normalized_refresh:
                    raise CredentialStorageError(
                        "The server did not issue a refresh token for remembered login."
                    )
                self.save_refresh_token(normalized_refresh)
            else:
                self.clear_refresh_token()
        except Exception as exc:
            self._best_effort_revoke(access_token, normalized_refresh)
            self._discard_local_session()
            if isinstance(exc, CredentialStorageError):
                raise
            raise CredentialStorageError("Remember Me could not be enabled securely.") from exc

        with self._session_lock:
            self._access_token = access_token
            self._refresh_token = normalized_refresh
            self._remembered = remembered
            self._session_generation += 1
            return self.session_credentials()

    def restore_saved_session(self) -> dict[str, object] | None:
        saved_refresh = self.load_refresh_token()
        if not saved_refresh:
            return None
        with self._refresh_lock:
            try:
                payload = self.refresh_session(saved_refresh)
                self.install_session(payload, remembered=True)
                return payload
            except Exception:
                self._discard_local_session()
                raise

    def refresh_current_session(self) -> dict[str, object]:
        with self._refresh_lock:
            credentials = self.session_credentials()
            if not credentials.refresh_token:
                raise ApiResponseError(401, "No refresh-capable desktop session is available.")
            try:
                payload = self.refresh_session(credentials.refresh_token)
                self.install_session(payload, remembered=credentials.remembered)
                return payload
            except Exception:
                self._discard_local_session()
                raise

    def logout_current_session(self) -> LogoutResult:
        credentials = self.session_credentials()
        server_confirmed = True
        warning_parts: list[str] = []
        try:
            if credentials.access_token or credentials.refresh_token:
                self.logout(
                    credentials.access_token,
                    refresh_token=credentials.refresh_token,
                )
        except Exception:
            server_confirmed = False
            warning_parts.append("Server revocation could not be confirmed.")
        credential_cleared = True
        try:
            self.clear_refresh_token()
        except CredentialStorageError:
            credential_cleared = False
            warning_parts.append("The operating-system saved login could not be removed.")
        finally:
            self._clear_memory_session()
        return LogoutResult(
            server_confirmed=server_confirmed,
            credential_cleared=credential_cleared,
            warning=" ".join(warning_parts) or None,
        )

    def _refresh_after_unauthorized(self, failed_access_token: str) -> str | None:
        with self._refresh_lock:
            credentials = self.session_credentials()
            if credentials.access_token and credentials.access_token != failed_access_token:
                return credentials.access_token
            if not credentials.refresh_token:
                if credentials.access_token == failed_access_token:
                    self._discard_local_session()
                return None
            try:
                payload = self.refresh_session(credentials.refresh_token)
                replacement = self.install_session(payload, remembered=credentials.remembered)
                return replacement.access_token
            except Exception:
                self._discard_local_session()
                return None

    def _best_effort_revoke(
        self,
        access_token: str | None,
        refresh_token: str | None,
    ) -> None:
        try:
            self.logout(access_token, refresh_token=refresh_token)
        except Exception:
            return

    def _clear_memory_session(self) -> None:
        with self._session_lock:
            self._access_token = None
            self._refresh_token = None
            self._remembered = False
            self._session_generation += 1

    def _discard_local_session(self) -> None:
        try:
            self.clear_refresh_token()
        except CredentialStorageError:
            pass
        finally:
            self._clear_memory_session()

    def list_products(
        self, token: str, *, include_archived: bool = False
    ) -> list[dict[str, object]]:
        path = "/api/v1/catalog/products"
        if include_archived:
            path += "?include_archived=true"
        response = self.request("GET", path, token=token)
        return response if isinstance(response, list) else []

    def get_product(self, token: str, product_id: str) -> dict[str, object]:
        response = self.request("GET", f"/api/v1/catalog/products/{product_id}", token=token)
        return response if isinstance(response, dict) else {}

    def create_product(
        self,
        token: str,
        *,
        name: str | None = None,
        sku: str | None = None,
        payload: dict[str, object] | None = None,
    ) -> dict[str, object]:
        product_payload: dict[str, object] = dict(payload or {})
        if name is not None:
            product_payload["name"] = name
        if sku:
            product_payload["sku"] = sku
        response = self.request(
            "POST",
            "/api/v1/catalog/products",
            token=token,
            json=product_payload,
            timeout=10.0,
        )
        return response if isinstance(response, dict) else {}

    def update_product(
        self,
        token: str,
        product_id: str,
        payload: dict[str, object],
    ) -> dict[str, object]:
        response = self.request(
            "PATCH",
            f"/api/v1/catalog/products/{product_id}",
            token=token,
            json=payload,
            timeout=10.0,
        )
        return response if isinstance(response, dict) else {}

    def archive_product(self, token: str, product_id: str) -> dict[str, object]:
        response = self.request(
            "DELETE",
            f"/api/v1/catalog/products/{product_id}",
            token=token,
            timeout=10.0,
        )
        return response if isinstance(response, dict) else {}

    def permanently_delete_product(self, token: str, product_id: str) -> dict[str, object]:
        response = self.request(
            "DELETE",
            f"/api/v1/catalog/products/{product_id}/permanent",
            token=token,
            timeout=10.0,
        )
        return response if isinstance(response, dict) else {}

    def upload_product_image(
        self,
        token: str,
        product_id: str,
        file_path: str,
    ) -> dict[str, object]:
        try:
            with open(file_path, "rb") as handle:
                response = httpx.post(
                    f"{self.base_url}/api/v1/catalog/products/{product_id}/images/upload",
                    headers=self._headers(token),
                    files={"file": (file_path, handle)},
                    timeout=30.0,
                    follow_redirects=True,
                )
        except httpx.RequestError as exc:
            raise ApiResponseError(
                0,
                f"Unable to connect to {self.base_url}: {exc}",
                url=f"{self.base_url}/api/v1/catalog/products/{product_id}/images/upload",
            ) from exc
        if response.status_code >= 400:
            try:
                payload = response.json()
                detail = jsonlib.dumps(payload, ensure_ascii=True, default=str)
            except Exception:
                detail = response.text or "No response body."
            raise ApiResponseError(response.status_code, detail, url=str(response.request.url))
        payload = response.json()
        return payload if isinstance(payload, dict) else {}

    def upload_product_video(
        self,
        token: str,
        product_id: str,
        file_path: str,
    ) -> dict[str, object]:
        endpoint = f"/api/v1/catalog/products/{product_id}/videos/upload"
        try:
            with open(file_path, "rb") as handle:
                response = httpx.post(
                    f"{self.base_url}{endpoint}",
                    headers=self._headers(token),
                    files={"file": (file_path, handle, "video/mp4")},
                    timeout=180.0,
                    follow_redirects=True,
                )
        except httpx.RequestError as exc:
            raise ApiResponseError(
                0,
                f"Unable to connect to {self.base_url}: {exc}",
                url=f"{self.base_url}{endpoint}",
            ) from exc
        if response.status_code >= 400:
            try:
                payload = response.json()
                detail = jsonlib.dumps(payload, ensure_ascii=True, default=str)
            except Exception:
                detail = response.text or "No response body."
            raise ApiResponseError(response.status_code, detail, url=str(response.request.url))
        payload = response.json()
        return payload if isinstance(payload, dict) else {}

    def list_categories(self, token: str) -> list[dict[str, object]]:
        response = self.request("GET", "/api/v1/catalog/categories", token=token)
        return response if isinstance(response, list) else []

    def create_category(self, token: str, payload: dict[str, object]) -> dict[str, object]:
        response = self.request("POST", "/api/v1/catalog/categories", token=token, json=payload)
        return response if isinstance(response, dict) else {}

    def list_brands(self, token: str) -> list[dict[str, object]]:
        response = self.request("GET", "/api/v1/catalog/brands", token=token)
        return response if isinstance(response, list) else []

    def create_brand(self, token: str, payload: dict[str, object]) -> dict[str, object]:
        response = self.request("POST", "/api/v1/catalog/brands", token=token, json=payload)
        return response if isinstance(response, dict) else {}

    def get_product_code_suggestion(self, token: str) -> dict[str, object]:
        response = self.request("GET", "/api/v1/catalog/products/code-suggestion", token=token)
        return response if isinstance(response, dict) else {}

    def list_customers(self, token: str) -> list[dict[str, object]]:
        response = self.request("GET", "/api/v1/customers", token=token)
        return response if isinstance(response, list) else []

    def create_customer(
        self,
        token: str,
        *,
        full_name: str,
        phone: str | None = None,
        email: str | None = None,
    ) -> dict[str, object]:
        payload: dict[str, object] = {"full_name": full_name}
        if phone:
            payload["phone"] = phone
        if email:
            payload["email"] = email
        response = self.request("POST", "/api/v1/customers", token=token, json=payload)
        return response if isinstance(response, dict) else {}

    def list_stock(self, token: str) -> list[dict[str, object]]:
        response = self.request("GET", "/api/v1/inventory/stock", token=token)
        return response if isinstance(response, list) else []

    def list_orders(self, token: str) -> list[dict[str, object]]:
        response = self.request("GET", "/api/v1/orders", token=token)
        return response if isinstance(response, list) else []

    def get_dashboard_summary(self, token: str) -> dict[str, object]:
        response = self.request("GET", "/api/v1/reports/dashboard-summary", token=token)
        return response if isinstance(response, dict) else {}

    def get_woocommerce_config(self, token: str) -> dict[str, object]:
        response = self.request("GET", "/api/v1/woocommerce/config", token=token)
        return response if isinstance(response, dict) else {}

    def save_woocommerce_config(
        self,
        token: str,
        *,
        site_url: str,
        consumer_key: str,
        consumer_secret: str,
        webhook_secret: str | None = None,
        wordpress_username: str | None = None,
        wordpress_application_password: str | None = None,
    ) -> dict[str, object]:
        payload: dict[str, object] = {
            "site_url": site_url,
            "consumer_key": consumer_key,
            "consumer_secret": consumer_secret,
        }
        if webhook_secret:
            payload["webhook_secret"] = webhook_secret
        if wordpress_username:
            payload["wordpress_username"] = wordpress_username
        if wordpress_application_password:
            payload["wordpress_application_password"] = wordpress_application_password
        response = self.request(
            "PUT",
            "/api/v1/woocommerce/config",
            token=token,
            json=payload,
            timeout=10.0,
        )
        return response if isinstance(response, dict) else {}

    def test_woocommerce_connection(self, token: str) -> dict[str, object]:
        response = self.request(
            "POST",
            "/api/v1/woocommerce/test-connection",
            token=token,
            timeout=15.0,
        )
        return response if isinstance(response, dict) else {}

    def run_woocommerce_sync(
        self, token: str, *, mode: str = "incremental"
    ) -> dict[str, object]:
        params = {"mode": mode} if mode != "incremental" else None
        response = self.request(
            "POST",
            "/api/v1/woocommerce/sync",
            token=token,
            params=params,
            # The API only queues the durable job; remote work belongs to the
            # worker, so this should return as quickly as an ordinary write.
            timeout=10.0,
        )
        return response if isinstance(response, dict) else {}

    def list_woocommerce_sync_runs(self, token: str) -> list[dict[str, object]]:
        response = self.request("GET", "/api/v1/woocommerce/sync-runs", token=token)
        return response if isinstance(response, list) else []

    def list_woocommerce_conflicts(self, token: str) -> list[dict[str, object]]:
        response = self.request("GET", "/api/v1/woocommerce/conflicts", token=token)
        return response if isinstance(response, list) else []

    def list_companies(self, token: str) -> list[dict[str, object]]:
        response = self.request("GET", "/api/v1/tenancy/companies", token=token)
        return response if isinstance(response, list) else []

    def update_company(
        self,
        token: str,
        company_id: str,
        payload: dict[str, object],
    ) -> dict[str, object]:
        response = self.request(
            "PATCH",
            f"/api/v1/tenancy/companies/{company_id}",
            token=token,
            json=payload,
        )
        return response if isinstance(response, dict) else {}

    def list_users(self, token: str) -> list[dict[str, object]]:
        response = self.request("GET", "/api/v1/identity/users", token=token)
        return response if isinstance(response, list) else []

    def create_user(self, token: str, payload: dict[str, object]) -> dict[str, object]:
        response = self.request("POST", "/api/v1/identity/users", token=token, json=payload)
        return response if isinstance(response, dict) else {}

    def update_user(
        self,
        token: str,
        user_id: str,
        payload: dict[str, object],
    ) -> dict[str, object]:
        response = self.request(
            "PATCH",
            f"/api/v1/identity/users/{user_id}",
            token=token,
            json=payload,
        )
        return response if isinstance(response, dict) else {}

    def reset_user_password(
        self,
        token: str,
        user_id: str,
        password: str,
    ) -> dict[str, object]:
        response = self.request(
            "POST",
            f"/api/v1/identity/users/{user_id}/reset-password",
            token=token,
            json={"password": password},
        )
        return response if isinstance(response, dict) else {}

    def list_roles(self, token: str) -> list[dict[str, object]]:
        response = self.request("GET", "/api/v1/identity/roles", token=token)
        return response if isinstance(response, list) else []

    def create_role(self, token: str, payload: dict[str, object]) -> dict[str, object]:
        response = self.request("POST", "/api/v1/identity/roles", token=token, json=payload)
        return response if isinstance(response, dict) else {}

    def get_license_status(self, token: str) -> dict[str, object]:
        response = self.request("GET", "/api/v1/licensing/status", token=token)
        return response if isinstance(response, dict) else {}

    def validate_license(self, token: str) -> dict[str, object]:
        response = self.request("POST", "/api/v1/licensing/validate", token=token)
        return response if isinstance(response, dict) else {}

    def activate_license(
        self,
        token: str,
        *,
        license_key: str,
        plan: str,
    ) -> dict[str, object]:
        response = self.request(
            "POST",
            "/api/v1/licensing/activate",
            token=token,
            json={"license_key": license_key, "plan": plan},
        )
        return response if isinstance(response, dict) else {}

    def revoke_license(self, token: str, reason: str | None = None) -> dict[str, object]:
        response = self.request(
            "POST",
            "/api/v1/licensing/revoke",
            token=token,
            json={"reason": reason},
        )
        return response if isinstance(response, dict) else {}

    def get_diagnostics_summary(self, token: str) -> dict[str, object]:
        response = self.request("GET", "/api/v1/support/diagnostics", token=token)
        return response if isinstance(response, dict) else {}

    def list_vendors(self, token: str) -> list[dict[str, object]]:
        response = self.request("GET", "/api/v1/marketplace/vendors", token=token)
        return response if isinstance(response, list) else []

    def get_vendor(self, token: str, vendor_id: str) -> dict[str, object]:
        response = self.request(
            "GET",
            f"/api/v1/marketplace/vendors/{vendor_id}",
            token=token,
        )
        return response if isinstance(response, dict) else {}

    def create_vendor(self, token: str, payload: dict[str, object]) -> dict[str, object]:
        response = self.request("POST", "/api/v1/marketplace/vendors", token=token, json=payload)
        return response if isinstance(response, dict) else {}

    def update_vendor(
        self,
        token: str,
        vendor_id: str,
        payload: dict[str, object],
    ) -> dict[str, object]:
        response = self.request(
            "PUT",
            f"/api/v1/marketplace/vendors/{vendor_id}",
            token=token,
            json=payload,
        )
        return response if isinstance(response, dict) else {}

    def approve_vendor(self, token: str, vendor_id: str) -> dict[str, object]:
        response = self.request(
            "POST",
            f"/api/v1/marketplace/vendors/{vendor_id}/approve",
            token=token,
        )
        return response if isinstance(response, dict) else {}

    def pause_vendor(
        self,
        token: str,
        vendor_id: str,
        reason: str | None = None,
    ) -> dict[str, object]:
        response = self.request(
            "POST",
            f"/api/v1/marketplace/vendors/{vendor_id}/pause",
            token=token,
            json={"reason": reason},
        )
        return response if isinstance(response, dict) else {}

    def reactivate_vendor(
        self,
        token: str,
        vendor_id: str,
        reason: str | None = None,
    ) -> dict[str, object]:
        response = self.request(
            "POST",
            f"/api/v1/marketplace/vendors/{vendor_id}/reactivate",
            token=token,
            json={"reason": reason},
        )
        return response if isinstance(response, dict) else {}

    def stop_vendor(
        self,
        token: str,
        vendor_id: str,
        reason: str | None = None,
    ) -> dict[str, object]:
        response = self.request(
            "POST",
            f"/api/v1/marketplace/vendors/{vendor_id}/stop",
            token=token,
            json={"reason": reason},
        )
        return response if isinstance(response, dict) else {}

    def list_vendor_products(self, token: str, vendor_id: str) -> list[dict[str, object]]:
        response = self.request(
            "GET",
            f"/api/v1/marketplace/vendors/{vendor_id}/products",
            token=token,
        )
        return response if isinstance(response, list) else []

    def list_current_vendor_products(self, token: str) -> list[dict[str, object]]:
        response = self.request("GET", "/api/v1/marketplace/vendor/products", token=token)
        return response if isinstance(response, list) else []

    def list_current_vendor_catalog_products(
        self, token: str, *, include_archived: bool = False
    ) -> list[dict[str, object]]:
        response = self.request(
            "GET",
            "/api/v1/vendor/catalog/products",
            token=token,
            params={"include_archived": include_archived},
        )
        return response if isinstance(response, list) else []

    def create_current_vendor_product(
        self, token: str, payload: dict[str, object]
    ) -> dict[str, object]:
        response = self.request(
            "POST", "/api/v1/vendor/catalog/products", token=token, json=payload
        )
        return response if isinstance(response, dict) else {}

    def update_current_vendor_product(
        self, token: str, product_id: str, payload: dict[str, object]
    ) -> dict[str, object]:
        response = self.request(
            "PATCH", f"/api/v1/vendor/catalog/products/{product_id}", token=token, json=payload
        )
        return response if isinstance(response, dict) else {}

    def update_current_vendor_order_item_status(
        self, token: str, vendor_order_item_id: str, status: str, reason: str | None = None
    ) -> dict[str, object]:
        payload: dict[str, object] = {"status": status}
        if reason:
            payload["reason"] = reason
        response = self.request(
            "POST",
            f"/api/v1/vendor/order-items/{vendor_order_item_id}/status",
            token=token,
            json=payload,
        )
        return response if isinstance(response, dict) else {}

    def create_current_vendor_stock_movement(
        self, token: str, payload: dict[str, object]
    ) -> dict[str, object]:
        response = self.request("POST", "/api/v1/vendor/stock/movements", token=token, json=payload)
        return response if isinstance(response, dict) else {}

    def assign_vendor_product(
        self,
        token: str,
        payload: dict[str, object],
    ) -> dict[str, object]:
        response = self.request(
            "POST",
            "/api/v1/marketplace/vendor-products/assign",
            token=token,
            json=payload,
        )
        return response if isinstance(response, dict) else {}

    def approve_vendor_product(
        self,
        token: str,
        vendor_id: str,
        product_id: str,
    ) -> dict[str, object]:
        response = self.request(
            "POST",
            f"/api/v1/marketplace/vendors/{vendor_id}/products/{product_id}/approve",
            token=token,
        )
        return response if isinstance(response, dict) else {}

    def list_vendor_order_items(self, token: str, vendor_id: str) -> list[dict[str, object]]:
        response = self.request(
            "GET",
            f"/api/v1/marketplace/vendors/{vendor_id}/order-items",
            token=token,
        )
        return response if isinstance(response, list) else []

    def list_current_vendor_orders(self, token: str) -> list[dict[str, object]]:
        response = self.request("GET", "/api/v1/marketplace/vendor/orders", token=token)
        return response if isinstance(response, list) else []

    def list_vendor_settlements(self, token: str, vendor_id: str) -> list[dict[str, object]]:
        response = self.request(
            "GET",
            f"/api/v1/marketplace/vendors/{vendor_id}/settlements",
            token=token,
        )
        return response if isinstance(response, list) else []

    def list_current_vendor_settlements(self, token: str) -> list[dict[str, object]]:
        response = self.request("GET", "/api/v1/marketplace/vendor/settlements", token=token)
        return response if isinstance(response, list) else []

    def create_vendor_settlement(
        self,
        token: str,
        payload: dict[str, object],
    ) -> dict[str, object]:
        response = self.request(
            "POST",
            "/api/v1/marketplace/settlements",
            token=token,
            json=payload,
        )
        return response if isinstance(response, dict) else {}

    def list_commission_rules(
        self,
        token: str,
        vendor_id: str | None = None,
    ) -> list[dict[str, object]]:
        params = {"vendor_id": vendor_id} if vendor_id else None
        response = self.request(
            "GET",
            "/api/v1/marketplace/commission-rules",
            token=token,
            params=params,
        )
        return response if isinstance(response, list) else []

    def create_commission_rule(self, token: str, payload: dict[str, object]) -> dict[str, object]:
        response = self.request(
            "POST",
            "/api/v1/marketplace/commission-rules",
            token=token,
            json=payload,
        )
        return response if isinstance(response, dict) else {}

    def update_commission_rule(
        self,
        token: str,
        rule_id: str,
        payload: dict[str, object],
    ) -> dict[str, object]:
        response = self.request(
            "PUT",
            f"/api/v1/marketplace/commission-rules/{rule_id}",
            token=token,
            json=payload,
        )
        return response if isinstance(response, dict) else {}

    def get_current_vendor(self, token: str) -> dict[str, object]:
        response = self.request("GET", "/api/v1/marketplace/vendor/me", token=token)
        return response if isinstance(response, dict) else {}

    def get_current_vendor_dashboard(self, token: str) -> dict[str, object]:
        response = self.request("GET", "/api/v1/marketplace/vendor/dashboard", token=token)
        return response if isinstance(response, dict) else {}

    def list_accounts(self, token: str) -> list[dict[str, object]]:
        response = self.request("GET", "/api/v1/accounting/accounts", token=token)
        return response if isinstance(response, list) else []

    def create_account(self, token: str, payload: dict[str, object]) -> dict[str, object]:
        response = self.request(
            "POST",
            "/api/v1/accounting/accounts",
            token=token,
            json=payload,
        )
        return response if isinstance(response, dict) else {}

    def update_account(
        self,
        token: str,
        account_id: str,
        payload: dict[str, object],
    ) -> dict[str, object]:
        response = self.request(
            "PUT",
            f"/api/v1/accounting/accounts/{account_id}",
            token=token,
            json=payload,
        )
        return response if isinstance(response, dict) else {}

    def list_periods(self, token: str) -> list[dict[str, object]]:
        response = self.request("GET", "/api/v1/accounting/periods", token=token)
        return response if isinstance(response, list) else []

    def create_period(self, token: str, payload: dict[str, object]) -> dict[str, object]:
        response = self.request(
            "POST",
            "/api/v1/accounting/periods",
            token=token,
            json=payload,
        )
        return response if isinstance(response, dict) else {}

    def update_period(
        self,
        token: str,
        period_id: str,
        payload: dict[str, object],
    ) -> dict[str, object]:
        response = self.request(
            "PUT",
            f"/api/v1/accounting/periods/{period_id}",
            token=token,
            json=payload,
        )
        return response if isinstance(response, dict) else {}

    def list_journal_entries(self, token: str) -> list[dict[str, object]]:
        response = self.request("GET", "/api/v1/accounting/journal-entries", token=token)
        return response if isinstance(response, list) else []

    def create_journal_entry(self, token: str, payload: dict[str, object]) -> dict[str, object]:
        response = self.request(
            "POST",
            "/api/v1/accounting/journal-entries",
            token=token,
            json=payload,
        )
        return response if isinstance(response, dict) else {}

    def list_vendor_ledger_entries(
        self,
        token: str,
        vendor_id: str | None = None,
    ) -> list[dict[str, object]]:
        params = {"vendor_id": vendor_id} if vendor_id else None
        response = self.request(
            "GET",
            "/api/v1/accounting/vendor-ledger",
            token=token,
            params=params,
        )
        return response if isinstance(response, list) else []

    def list_cash_books(self, token: str) -> list[dict[str, object]]:
        response = self.request("GET", "/api/v1/accounting/cash-books", token=token)
        return response if isinstance(response, list) else []

    def create_cash_book(self, token: str, payload: dict[str, object]) -> dict[str, object]:
        response = self.request(
            "POST",
            "/api/v1/accounting/cash-books",
            token=token,
            json=payload,
        )
        return response if isinstance(response, dict) else {}

    def list_bank_accounts(self, token: str) -> list[dict[str, object]]:
        response = self.request("GET", "/api/v1/accounting/bank-accounts", token=token)
        return response if isinstance(response, list) else []

    def create_bank_account(self, token: str, payload: dict[str, object]) -> dict[str, object]:
        response = self.request(
            "POST",
            "/api/v1/accounting/bank-accounts",
            token=token,
            json=payload,
        )
        return response if isinstance(response, dict) else {}

    def list_expenses(self, token: str) -> list[dict[str, object]]:
        response = self.request("GET", "/api/v1/accounting/expenses", token=token)
        return response if isinstance(response, list) else []

    def create_expense(self, token: str, payload: dict[str, object]) -> dict[str, object]:
        response = self.request(
            "POST",
            "/api/v1/accounting/expenses",
            token=token,
            json=payload,
        )
        return response if isinstance(response, dict) else {}

    def create_vendor_account(self, token: str, payload: dict[str, object]) -> dict[str, object]:
        response = self.request(
            "POST", "/api/v1/marketplace/vendors/with-account", token=token, json=payload
        )
        return response if isinstance(response, dict) else {}

    def change_vendor_status(
        self, token: str, vendor_id: str, status: str, reason: str
    ) -> dict[str, object]:
        response = self.request(
            "PATCH",
            f"/api/v1/marketplace/vendors/{vendor_id}/status",
            token=token,
            json={"status": status, "reason": reason},
        )
        return response if isinstance(response, dict) else {}

    def get_ledger_overview(self, token: str) -> dict[str, object]:
        response = self.request("GET", "/api/v1/ledger/overview", token=token)
        return response if isinstance(response, dict) else {}

    def list_ledger_accounts(self, token: str) -> list[dict[str, object]]:
        response = self.request("GET", "/api/v1/ledger/accounts", token=token)
        return response if isinstance(response, list) else []

    def list_ledger_journals(
        self,
        token: str,
        vendor_id: str | None = None,
        *,
        account_id: str | None = None,
        source_type: str | None = None,
        status: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
    ) -> list[dict[str, object]]:
        params = {
            key: value
            for key, value in {
                "vendor_id": vendor_id,
                "account_id": account_id,
                "source_type": source_type,
                "status": status,
                "date_from": date_from,
                "date_to": date_to,
            }.items()
            if value
        }
        response = self.request(
            "GET", "/api/v1/ledger/journals", token=token, params=params or None
        )
        return response if isinstance(response, list) else []

    def get_trial_balance(
        self,
        token: str,
        *,
        date_from: str | None = None,
        date_to: str | None = None,
    ) -> list[dict[str, object]]:
        params = {
            key: value
            for key, value in {"date_from": date_from, "date_to": date_to}.items()
            if value
        }
        response = self.request(
            "GET", "/api/v1/ledger/trial-balance", token=token, params=params or None
        )
        return response if isinstance(response, list) else []

    def get_profit_loss(
        self,
        token: str,
        *,
        date_from: str | None = None,
        date_to: str | None = None,
    ) -> dict[str, object]:
        params = {
            key: value
            for key, value in {"date_from": date_from, "date_to": date_to}.items()
            if value
        }
        response = self.request(
            "GET", "/api/v1/ledger/reports/profit-loss", token=token, params=params or None
        )
        return response if isinstance(response, dict) else {}

    def get_balance_sheet(self, token: str, *, date_to: str | None = None) -> dict[str, object]:
        params = {"date_to": date_to} if date_to else None
        response = self.request(
            "GET", "/api/v1/ledger/reports/balance-sheet", token=token, params=params
        )
        return response if isinstance(response, dict) else {}

    def get_cash_flow(
        self,
        token: str,
        *,
        date_from: str | None = None,
        date_to: str | None = None,
    ) -> dict[str, object]:
        params = {
            key: value
            for key, value in {"date_from": date_from, "date_to": date_to}.items()
            if value
        }
        response = self.request(
            "GET", "/api/v1/ledger/reports/cash-flow", token=token, params=params or None
        )
        return response if isinstance(response, dict) else {}

    def get_vendor_payables(
        self, token: str, *, as_of: str | None = None
    ) -> list[dict[str, object]]:
        params = {"as_of": as_of} if as_of else None
        response = self.request(
            "GET", "/api/v1/ledger/reports/vendor-payables", token=token, params=params
        )
        return response if isinstance(response, list) else []

    def get_ledger_inventory_report(
        self,
        token: str,
        *,
        vendor_id: str | None = None,
        product_id: str | None = None,
        warehouse_id: str | None = None,
    ) -> list[dict[str, object]]:
        params = {
            key: value
            for key, value in {
                "vendor_id": vendor_id,
                "product_id": product_id,
                "warehouse_id": warehouse_id,
            }.items()
            if value
        }
        response = self.request(
            "GET", "/api/v1/ledger/reports/inventory", token=token, params=params or None
        )
        return response if isinstance(response, list) else []

    def get_vendor_ledger_overview(
        self, token: str, vendor_id: str | None = None
    ) -> dict[str, object]:
        path = (
            f"/api/v1/ledger/vendors/{vendor_id}/overview"
            if vendor_id
            else "/api/v1/vendor/ledger/overview"
        )
        response = self.request("GET", path, token=token)
        return response if isinstance(response, dict) else {}

    def list_authoritative_vendor_ledger(
        self,
        token: str,
        vendor_id: str | None = None,
        *,
        date_from: str | None = None,
        date_to: str | None = None,
    ) -> list[dict[str, object]]:
        path = (
            f"/api/v1/ledger/vendors/{vendor_id}/ledger"
            if vendor_id
            else "/api/v1/vendor/ledger/entries"
        )
        params = {
            key: value
            for key, value in {"date_from": date_from, "date_to": date_to}.items()
            if value
        }
        response = self.request("GET", path, token=token, params=params or None)
        return response if isinstance(response, list) else []

    def list_vendor_stock(
        self, token: str, vendor_id: str | None = None
    ) -> list[dict[str, object]]:
        path = (
            f"/api/v1/ledger/vendors/{vendor_id}/stock"
            if vendor_id
            else "/api/v1/vendor/stock/overview"
        )
        response = self.request("GET", path, token=token)
        return response if isinstance(response, list) else []

    def list_vendor_stock_movements(
        self,
        token: str,
        vendor_id: str | None = None,
        *,
        product_id: str | None = None,
        warehouse_id: str | None = None,
        movement_type: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
    ) -> list[dict[str, object]]:
        path = (
            f"/api/v1/ledger/vendors/{vendor_id}/stock/movements"
            if vendor_id
            else "/api/v1/vendor/stock/movements"
        )
        params = {
            key: value
            for key, value in {
                "product_id": product_id,
                "warehouse_id": warehouse_id,
                "movement_type": movement_type,
                "date_from": date_from,
                "date_to": date_to,
            }.items()
            if value
        }
        response = self.request("GET", path, token=token, params=params or None)
        return response if isinstance(response, list) else []

    def get_reconciliation(self, token: str) -> list[dict[str, object]]:
        response = self.request("GET", "/api/v1/ledger/reconciliation", token=token)
        return response if isinstance(response, list) else []

    def list_vendor_orders_for_admin(
        self,
        token: str,
        vendor_id: str,
        *,
        date_from: str | None = None,
        date_to: str | None = None,
        order_status: str | None = None,
        payment_status: str | None = None,
        limit: int = 10,
        offset: int = 0,
    ) -> list[dict[str, object]]:
        params = {
            key: value
            for key, value in {
                "date_from": date_from,
                "date_to": date_to,
                "order_status": order_status,
                "payment_status": payment_status,
                "limit": limit,
                "offset": offset,
            }.items()
            if value is not None and value != ""
        }
        response = self.request(
            "GET",
            f"/api/v1/ledger/vendors/{vendor_id}/orders",
            token=token,
            params=params or None,
        )
        return response if isinstance(response, list) else []

    def list_vendor_settlements_for_admin(
        self,
        token: str,
        vendor_id: str,
        *,
        date_from: str | None = None,
        date_to: str | None = None,
        status: str | None = None,
    ) -> list[dict[str, object]]:
        params = {
            key: value
            for key, value in {
                "date_from": date_from,
                "date_to": date_to,
                "status": status,
            }.items()
            if value
        }
        response = self.request(
            "GET",
            f"/api/v1/ledger/vendors/{vendor_id}/settlements",
            token=token,
            params=params or None,
        )
        return response if isinstance(response, list) else []

    def list_own_vendor_orders(
        self,
        token: str,
        *,
        date_from: str | None = None,
        date_to: str | None = None,
        order_status: str | None = None,
        payment_status: str | None = None,
        limit: int = 10,
        offset: int = 0,
    ) -> list[dict[str, object]]:
        params = {
            key: value
            for key, value in {
                "date_from": date_from,
                "date_to": date_to,
                "order_status": order_status,
                "payment_status": payment_status,
                "limit": limit,
                "offset": offset,
            }.items()
            if value is not None and value != ""
        }
        response = self.request("GET", "/api/v1/vendor/orders", token=token, params=params or None)
        return response if isinstance(response, list) else []

    def list_own_vendor_settlements(
        self,
        token: str,
        *,
        date_from: str | None = None,
        date_to: str | None = None,
        status: str | None = None,
    ) -> list[dict[str, object]]:
        params = {
            key: value
            for key, value in {
                "date_from": date_from,
                "date_to": date_to,
                "status": status,
            }.items()
            if value
        }
        response = self.request(
            "GET", "/api/v1/vendor/settlements", token=token, params=params or None
        )
        return response if isinstance(response, list) else []

    def list_vendor_users_for_admin(self, token: str, vendor_id: str) -> list[dict[str, object]]:
        response = self.request(
            "GET", f"/api/v1/marketplace/vendors/{vendor_id}/users", token=token
        )
        return response if isinstance(response, list) else []

    def list_vendor_audit_for_admin(self, token: str, vendor_id: str) -> list[dict[str, object]]:
        response = self.request("GET", f"/api/v1/ledger/vendors/{vendor_id}/audit", token=token)
        return response if isinstance(response, list) else []

    def export_ledger_journals_csv(
        self,
        token: str,
        *,
        vendor_id: str | None = None,
        account_id: str | None = None,
        source_type: str | None = None,
        status: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
    ) -> str:
        params = {
            key: value
            for key, value in {
                "vendor_id": vendor_id,
                "account_id": account_id,
                "source_type": source_type,
                "status": status,
                "date_from": date_from,
                "date_to": date_to,
            }.items()
            if value
        }
        return self.download_text(
            "/api/v1/ledger/export/journals.csv", token=token, params=params or None
        )
