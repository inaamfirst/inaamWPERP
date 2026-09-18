from __future__ import annotations

import hashlib
import json as jsonlib
import logging
import mimetypes
import random
import re
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

import httpx
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from erp.packages.core.catalog_services import (
    archive_product,
    product_videos,
    require_company_id,
)
from erp.packages.core.config import get_settings
from erp.packages.core.db.models import (
    Brand,
    Category,
    Customer,
    CustomerAddress,
    ExternalResourceMap,
    Order,
    Product,
    ProductChannelListing,
    ProductCategoryLink,
    ProductImage,
    ProductVariant,
    ProductVideo,
    Setting,
    StockMovement,
    SyncConflict,
    SyncInboxLog,
    SyncOutbox,
    SyncRunLog,
    User,
    Vendor,
    VendorOrderItem,
    VendorProduct,
    Warehouse,
    new_uuid,
)
from erp.packages.core.schemas import (
    StockMovementCreate,
    SyncConflictResolveRequest,
    WooCommerceConfigRequest,
)
from erp.packages.core.security import decrypt_text, encrypt_text
from erp.packages.core.services import ServiceError, record_audit, utcnow

WOOCOMMERCE_SETTING_KEY = "woocommerce.credentials"
WOOCOMMERCE_VIDEO_META_KEY = "choiceoye_erp_product_videos"
WOOCOMMERCE_VIDEO_SCHEMA_VERSION = 1
CONNECTOR = "woocommerce"
WOOCOMMERCE_REST_MODES = ("pretty", "query")
WOOCOMMERCE_SYNC_MODES = (
    "incremental",
    "products",
    "full_products",
    "reconcile_products",
    "outbox",
)
WOOCOMMERCE_LAST_SYNC_KEYS = {
    "product": "last_products_sync",
    "order": "last_orders_sync",
}
WOOCOMMERCE_LEGACY_CUSTOMER_SYNC_KEY = "last_customers_sync"
WOOCOMMERCE_SYNC_READ_ENDPOINTS = (
    ("/products", "products"),
    ("/products/categories", "categories"),
    ("/products/brands", "brands"),
    ("/customers", "customers"),
    ("/orders", "orders"),
)
ALLOWED_RESOURCE_TYPES = {"product", "customer", "order", "category", "brand"}
ORDER_PROGRESS_STATUSES = ["pending", "confirmed", "packing", "ready", "dispatched", "delivered"]

LOGGER = logging.getLogger(__name__)
PRODUCT_IMAGE_SYNC_STATUSES = {"synced", "pending_add", "pending_update", "pending_remove"}
SYNC_RUN_ACTIVE_STATUSES = {"queued", "running"}
SYNC_JOB_LEASE_SECONDS = 10 * 60
SYNC_OUTBOX_STALE_SECONDS = 15 * 60
SYNC_PULL_PROGRESS_BATCH_SIZE = 50
REMOTE_RETRY_ATTEMPTS = 3
REMOTE_RETRY_MAX_SECONDS = 10.0
REMOTE_REQUEST_INTERVAL_SECONDS = 1.0
RATE_LIMIT_DEFAULT_DELAY_SECONDS = 60.0
RATE_LIMIT_MAX_DELAY_SECONDS = 15 * 60.0
RATE_LIMIT_MAX_RUN_ATTEMPTS = 8
SYNC_OUTBOX_MAX_ATTEMPTS = 8
WOOCOMMERCE_TIMESTAMP_OVERLAP = timedelta(seconds=1)

_REMOTE_REQUEST_PACING_LOCK = threading.Lock()
_REMOTE_REQUEST_NEXT_ALLOWED_AT: dict[str, float] = {}
# Some production hosts have an IPv6 DNS result for a store but no IPv6 route.
# Remembering the IPv4 fallback per origin avoids making every subsequent
# WooCommerce request wait for the same failed IPv6 connection attempt.
_REMOTE_FORCE_IPV4_ORIGINS: set[str] = set()


@dataclass(frozen=True)
class WooCommerceConfig:
    site_url: str
    consumer_key: str
    consumer_secret: str
    key_hint: str
    rest_api_mode: str | None = None
    wordpress_username: str | None = None
    wordpress_application_password: str | None = None
    webhook_secret: str | None = None


@dataclass(frozen=True)
class ConnectionTestResult:
    ok: bool
    status: str
    detail: str
    video_plugin_detected: bool = False
    video_plugin_compatible: bool = False
    video_plugin_version: str | None = None
    wordpress_max_upload_bytes: int | None = None


class ReusableFileBody:
    """Replayable streaming request body for bounded remote-upload retries."""

    def __init__(self, path: Path, chunk_size: int = 1024 * 1024) -> None:
        self.path = path
        self.chunk_size = chunk_size

    def __iter__(self):
        with self.path.open("rb") as handle:
            while chunk := handle.read(self.chunk_size):
                yield chunk


@dataclass(frozen=True)
class WooCommerceRequestResult:
    response: httpx.Response
    rest_api_mode: str
    auth_mode: str
    resource_path: str
    url: str


class WooCommerceRateLimitError(ServiceError):
    """A remote 429 that must defer the durable sync run instead of failing it."""

    def __init__(self, result: WooCommerceRequestResult, retry_after_seconds: float) -> None:
        super().__init__(
            429,
            format_remote_http_error(action="WooCommerce rate limit", result=result),
        )
        self.retry_after_seconds = retry_after_seconds


def woocommerce_sync_user_id(db: Session, company_id: str) -> str | None:
    """Return a local actor for sync-originated audit and inventory records."""

    return db.scalar(
        select(User.id)
        .where(User.company_id == company_id)
        .order_by(User.created_at, User.id)
        .limit(1)
    )


def normalize_site_url(site_url: str) -> str:
    value = site_url.strip().rstrip("/")
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ServiceError(422, "WooCommerce site URL must be a valid HTTP or HTTPS URL.")
    if parsed.username or parsed.password:
        raise ServiceError(422, "WooCommerce site URL must not contain credentials.")
    return value


def key_hint(consumer_key: str) -> str:
    if len(consumer_key) <= 8:
        return "********"
    return f"{consumer_key[:4]}...{consumer_key[-4:]}"


def normalize_rest_api_mode(rest_api_mode: object | None) -> str | None:
    if rest_api_mode is None:
        return None
    normalized = str(rest_api_mode).strip().lower()
    if normalized in WOOCOMMERCE_REST_MODES:
        return normalized
    return None


def update_woocommerce_setting_value(
    db: Session,
    *,
    company_id: str,
    updates: dict[str, object | None],
) -> Setting:
    # Lock and refresh the single company connector row before merging. This
    # prevents a checkpoint write from replacing newer credential, media, or
    # unrelated JSON values with a stale ORM copy on PostgreSQL.
    setting = get_setting(db, company_id, WOOCOMMERCE_SETTING_KEY, for_update=True)
    if setting is None:
        raise ServiceError(404, "WooCommerce is not configured.")
    current_value = dict(setting.value)
    current_value.update({key: value for key, value in updates.items() if value is not None})
    for key, value in updates.items():
        if value is None:
            current_value.pop(key, None)
    setting.value = current_value
    db.flush()
    db.refresh(setting)
    return setting


def store_woocommerce_rest_api_mode(
    db: Session,
    *,
    company_id: str,
    rest_api_mode: str,
) -> None:
    normalized_mode = normalize_rest_api_mode(rest_api_mode)
    if normalized_mode is None:
        return
    # This function is intentionally flush-free.  It is often called directly
    # after a remote request succeeds; flushing here could start a database
    # write transaction immediately before the next remote request.
    setting = get_setting(db, company_id, WOOCOMMERCE_SETTING_KEY)
    if setting is None:
        return
    value = dict(setting.value)
    if value.get("rest_api_mode") == normalized_mode:
        return
    value["rest_api_mode"] = normalized_mode
    setting.value = value


def woocommerce_rest_mode_candidates(rest_api_mode: object | None = None) -> list[str]:
    candidates: list[str] = []
    normalized = normalize_rest_api_mode(rest_api_mode)
    if normalized is not None:
        candidates.append(normalized)
    for mode in WOOCOMMERCE_REST_MODES:
        if mode not in candidates:
            candidates.append(mode)
    return candidates


def build_woocommerce_request_url(site_url: str, resource_path: str, rest_api_mode: str) -> str:
    base_url = normalize_site_url(site_url)
    normalized_path = resource_path if resource_path.startswith("/") else f"/{resource_path}"
    if rest_api_mode == "pretty":
        return f"{base_url}/wp-json/wc/v3{normalized_path}"
    if rest_api_mode == "query":
        return f"{base_url}/?rest_route=/wc/v3{normalized_path}"
    raise ServiceError(422, f"Unsupported WooCommerce REST mode: {rest_api_mode}.")


def build_wordpress_request_url(site_url: str, resource_path: str, rest_api_mode: str) -> str:
    base_url = normalize_site_url(site_url)
    normalized_path = resource_path if resource_path.startswith("/") else f"/{resource_path}"
    if rest_api_mode == "pretty":
        return f"{base_url}/wp-json/wp/v2{normalized_path}"
    if rest_api_mode == "query":
        return f"{base_url}/?rest_route=/wp/v2{normalized_path}"
    raise ServiceError(422, f"Unsupported WordPress REST mode: {rest_api_mode}.")


def build_wordpress_namespace_url(
    site_url: str, namespace_path: str, rest_api_mode: str
) -> str:
    base_url = normalize_site_url(site_url)
    normalized_path = namespace_path.lstrip("/")
    if rest_api_mode == "pretty":
        return f"{base_url}/wp-json/{normalized_path}"
    if rest_api_mode == "query":
        return f"{base_url}/?rest_route=/{normalized_path}"
    raise ServiceError(422, f"Unsupported WordPress REST mode: {rest_api_mode}.")


def extract_remote_response_detail(response: httpx.Response) -> str:
    try:
        payload = response.json()
    except Exception:
        payload = None

    if isinstance(payload, dict):
        parts: list[str] = []
        for key in ("message", "code", "data", "error"):
            value = payload.get(key)
            if value is not None and value != "":
                if key == "data" and isinstance(value, dict):
                    nested = {k: v for k, v in value.items() if k != "trace"}
                    parts.append(f"{key}={jsonlib.dumps(nested, ensure_ascii=True, default=str)}")
                else:
                    parts.append(f"{key}={value}")
        if parts:
            return "; ".join(parts)[:1000]
        return jsonlib.dumps(payload, ensure_ascii=True, default=str)[:1000]
    if isinstance(payload, list):
        return jsonlib.dumps(payload[:3], ensure_ascii=True, default=str)[:1000]

    text = (response.text or "").strip()
    if text:
        return text[:1000]
    return "No response body."


def remote_response_error_hint(response: httpx.Response, resource_path: str) -> str | None:
    try:
        payload = response.json()
    except Exception:
        payload = None
    if not isinstance(payload, dict):
        return None

    code = str(payload.get("code") or "")
    message = str(payload.get("message") or "")
    resource_label = resource_path.strip("/") or "this WooCommerce resource"

    if response.status_code in {401, 403} and (
        code == "woocommerce_rest_cannot_view" or "cannot list resources" in message.lower()
    ):
        return (
            f"the WooCommerce REST API key cannot read {resource_label}. "
            "Create a new WooCommerce REST API key for an Administrator or Shop Manager "
            "user with Read/Write permission, then save the new Consumer Key and "
            "Consumer Secret in the ERP."
        )
    if response.status_code in {401, 403} and (
        code.startswith("woocommerce_rest_authentication") or "signature" in message.lower()
    ):
        return (
            "WooCommerce rejected the Consumer Key/Secret. Copy both values from the "
            "same WooCommerce REST API key and save them again in the ERP."
        )
    return None


def format_remote_http_error(
    *,
    action: str,
    result: WooCommerceRequestResult,
) -> str:
    detail = extract_remote_response_detail(result.response)
    hint = remote_response_error_hint(result.response, result.resource_path)
    if hint:
        return (
            f"{action} failed: {hint} "
            f"Endpoint: {result.resource_path} using {result.rest_api_mode} REST mode "
            f"and {result.auth_mode} auth. "
            f"Remote response: HTTP {result.response.status_code}; {detail}"
        )
    return (
        f"{action} failed against WooCommerce resource {result.resource_path} "
        f"using {result.rest_api_mode} REST mode and {result.auth_mode} auth at {result.url} "
        f"(remote HTTP {result.response.status_code}): {detail}"
    )


def _retry_delay_seconds(response: httpx.Response | None, retry_number: int) -> float:
    if response is not None:
        retry_after = response.headers.get("Retry-After")
        if retry_after:
            try:
                return min(max(float(retry_after), 0.0), REMOTE_RETRY_MAX_SECONDS)
            except ValueError:
                pass
    return min(float(2**retry_number), REMOTE_RETRY_MAX_SECONDS)


def _rate_limit_delay_seconds(response: httpx.Response) -> float:
    """Return a bounded delay from Retry-After seconds or an HTTP date."""

    value = response.headers.get("Retry-After")
    if value:
        try:
            return min(max(float(value), 0.0), RATE_LIMIT_MAX_DELAY_SECONDS)
        except ValueError:
            try:
                retry_at = parsedate_to_datetime(value)
                if retry_at.tzinfo is None:
                    retry_at = retry_at.replace(tzinfo=UTC)
                return min(
                    max((retry_at - utcnow()).total_seconds(), 0.0),
                    RATE_LIMIT_MAX_DELAY_SECONDS,
                )
            except (TypeError, ValueError, IndexError, OverflowError):
                pass
    return RATE_LIMIT_DEFAULT_DELAY_SECONDS


def _pace_remote_request(url: str) -> None:
    """Serialize requests per remote origin at the production-safe one-per-second rate."""

    # Unit/local development runs use mocked connectors and do not represent a
    # shared live store. The managed worker is mandatory in production and is
    # the only process that needs this production safety gate.
    if not getattr(get_settings(), "worker_loop", False):
        return
    origin = f"{urlparse(url).scheme}://{urlparse(url).netloc}".lower()
    with _REMOTE_REQUEST_PACING_LOCK:
        now = time.monotonic()
        next_allowed = _REMOTE_REQUEST_NEXT_ALLOWED_AT.get(origin, now)
        delay = max(0.0, next_allowed - now)
        if delay:
            time.sleep(delay)
        _REMOTE_REQUEST_NEXT_ALLOWED_AT[origin] = time.monotonic() + REMOTE_REQUEST_INTERVAL_SECONDS


def _remote_origin(url: str) -> str:
    parsed = urlparse(url)
    return f"{parsed.scheme}://{parsed.netloc}".lower()


def _is_unreachable_network_error(exc: httpx.RequestError) -> bool:
    """Return true only for a missing network route, commonly IPv6-only DNS."""
    detail = str(exc).lower()
    return "network is unreachable" in detail or "errno 101" in detail


def _remote_request_over_ipv4(method: str, url: str, **kwargs: object) -> httpx.Response:
    """Repeat one request over IPv4 while retaining the HTTPS hostname/SNI."""
    # Binding the outbound socket to an IPv4 wildcard address makes httpx use
    # the A record without replacing the hostname in the URL.  The latter
    # would break TLS certificate validation and WordPress virtual hosts.
    transport = httpx.HTTPTransport(local_address="0.0.0.0")
    with httpx.Client(transport=transport) as client:
        return client.request(method, url, **kwargs)


def _remote_request_with_retry(
    method: str,
    url: str,
    **kwargs: object,
) -> httpx.Response:
    """Retry only temporary remote failures, while honoring a bounded Retry-After.

    Calls happen from the worker outside a database write transaction.  Keeping
    retries here makes rate limits observable/retryable without turning a 429
    into a destructive media operation.
    """

    last_request_error: httpx.RequestError | None = None
    origin = _remote_origin(url)
    force_ipv4 = origin in _REMOTE_FORCE_IPV4_ORIGINS
    for attempt in range(REMOTE_RETRY_ATTEMPTS):
        try:
            _pace_remote_request(url)
            response = (
                _remote_request_over_ipv4(method, url, **kwargs)
                if force_ipv4
                else httpx.request(method, url, **kwargs)
            )
        except httpx.RequestError as exc:
            last_request_error = exc
            response = None
            if not force_ipv4 and _is_unreachable_network_error(exc):
                force_ipv4 = True
                _REMOTE_FORCE_IPV4_ORIGINS.add(origin)
                LOGGER.warning(
                    "WooCommerce host %s has no usable default network route; retrying over IPv4.",
                    urlparse(url).netloc,
                )
        # Retrying a rate limit immediately only worsens the remote block. The
        # durable run scheduler receives the 429 and defers it instead.
        if response is not None and response.status_code == 429:
            return response
        if response is not None and response.status_code not in {502, 503, 504}:
            return response
        if attempt + 1 >= REMOTE_RETRY_ATTEMPTS:
            if response is not None:
                return response
            break
        delay = _retry_delay_seconds(response, attempt)
        LOGGER.warning(
            "Temporary WooCommerce/WordPress %s failure for %s; retrying in %.1fs.",
            response.status_code if response is not None else "network",
            urlparse(url).path,
            delay,
        )
        time.sleep(delay)
    if last_request_error is not None:
        raise last_request_error
    raise ServiceError(503, "Remote request failed before a response was received.")


def _woocommerce_request_once(
    db: Session,
    company_id: str,
    method: str,
    resource_path: str,
    *,
    rest_api_mode: str,
    auth_mode: str,
    json_data: dict | None = None,
    params: dict[str, object] | None = None,
    timeout: float = 10.0,
) -> WooCommerceRequestResult:
    config = load_woocommerce_config(db, company_id)
    if config is None:
        raise ServiceError(404, "WooCommerce is not configured.")
    url = build_woocommerce_request_url(config.site_url, resource_path, rest_api_mode)
    auth: tuple[str, str] | None = (config.consumer_key, config.consumer_secret)

    parsed = urlparse(url)
    merged_params = dict(parse_qsl(parsed.query))
    if params:
        stringified_params = {k: str(v) for k, v in params.items()}
        merged_params.update(stringified_params)
    safe_params = dict(merged_params)
    if auth_mode == "query":
        auth = None
        merged_params["consumer_key"] = config.consumer_key
        merged_params["consumer_secret"] = config.consumer_secret
        safe_params["consumer_key"] = config.key_hint
        safe_params["consumer_secret"] = "********"
    elif auth_mode != "basic":
        raise ServiceError(422, f"Unsupported WooCommerce auth mode: {auth_mode}.")
    request_url = urlunparse(parsed._replace(query=urlencode(merged_params, safe="/")))
    safe_url = urlunparse(parsed._replace(query=urlencode(safe_params, safe="/")))

    try:
        response = _remote_request_with_retry(
            method,
            request_url,
            auth=auth,
            json=json_data,
            params=None,
            timeout=timeout,
            follow_redirects=True,
        )
    except httpx.RequestError as exc:
        raise ServiceError(
            503,
            f"WooCommerce request to {resource_path} failed in {rest_api_mode} REST mode "
            f"with {auth_mode} auth: {exc}",
        ) from exc
    return WooCommerceRequestResult(
        response=response,
        rest_api_mode=rest_api_mode,
        auth_mode=auth_mode,
        resource_path=resource_path,
        url=safe_url,
    )


def get_setting(
    db: Session,
    company_id: str,
    key: str,
    *,
    for_update: bool = False,
) -> Setting | None:
    query = select(Setting).where(Setting.company_id == company_id, Setting.key == key)
    if for_update and db.get_bind().dialect.name != "sqlite":
        query = query.with_for_update()
    return db.scalar(query.execution_options(populate_existing=for_update))


def _format_woocommerce_utc_timestamp(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _woocommerce_second_precision_boundary(value: datetime, *, upper: bool) -> str:
    """Return an exclusive, whole-second WooCommerce window bound.

    WooCommerce's date query is exclusive and its persisted modification
    timestamps have whole-second precision. The lower bound overlaps by one
    second, while the upper bound remains the captured start second so records
    modified after the run begins cannot enter and shift offset-based pages.
    The next run's lower overlap safely retrieves the deferred boundary second.
    """

    normalized = value
    if normalized.tzinfo is None:
        normalized = normalized.replace(tzinfo=UTC)
    normalized = normalized.astimezone(UTC).replace(microsecond=0)
    if not upper:
        normalized -= WOOCOMMERCE_TIMESTAMP_OVERLAP
    return _format_woocommerce_utc_timestamp(normalized)


def _woocommerce_incremental_after(checkpoint: str) -> str:
    parsed = datetime.fromisoformat(checkpoint.replace("Z", "+00:00"))
    return _woocommerce_second_precision_boundary(parsed, upper=False)


def _woocommerce_timestamp_for_log(value: str | None) -> str:
    if value is None:
        return "not set"
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC).strftime("%Y-%m-%d %H:%M:%S")


def get_woocommerce_last_sync(
    db: Session,
    company_id: str,
    resource_type: str,
) -> str | None:
    key = WOOCOMMERCE_LAST_SYNC_KEYS.get(resource_type)
    if key is None:
        return None
    setting = get_setting(db, company_id, WOOCOMMERCE_SETTING_KEY)
    if setting is None:
        return None
    raw_value = setting.value.get(key)
    if not raw_value:
        return None
    try:
        parsed = datetime.fromisoformat(str(raw_value).replace("Z", "+00:00"))
    except ValueError:
        LOGGER.warning(
            "Ignoring invalid WooCommerce %s timestamp for company %s: %s",
            key,
            company_id,
            raw_value,
        )
        return None
    return _format_woocommerce_utc_timestamp(parsed)


def store_woocommerce_last_sync(
    db: Session,
    *,
    company_id: str,
    resource_type: str,
    sync_started_at: datetime,
) -> str:
    key = WOOCOMMERCE_LAST_SYNC_KEYS.get(resource_type)
    if key is None:
        raise ServiceError(422, f"WooCommerce {resource_type} sync does not support checkpoints.")
    timestamp = _format_woocommerce_utc_timestamp(sync_started_at)
    update_woocommerce_setting_value(
        db,
        company_id=company_id,
        updates={key: timestamp},
    )
    return timestamp


def normalize_woocommerce_sync_mode(sync_mode: str | None) -> str:
    normalized = str(sync_mode or "incremental").strip().lower()
    if normalized not in WOOCOMMERCE_SYNC_MODES:
        allowed = ", ".join(WOOCOMMERCE_SYNC_MODES)
        raise ServiceError(422, f"Unsupported WooCommerce sync mode. Expected one of: {allowed}.")
    return normalized


def configure_woocommerce(
    db: Session,
    *,
    company_id: str | None,
    user_id: str,
    payload: WooCommerceConfigRequest,
) -> Setting:
    scoped_company_id = require_company_id(company_id)
    site_url = normalize_site_url(payload.site_url)
    setting = get_setting(db, scoped_company_id, WOOCOMMERCE_SETTING_KEY)
    existing_value = dict(setting.value) if setting is not None else {}
    encrypted_value = {
        "site_url": encrypt_text(site_url),
        "consumer_key": encrypt_text(payload.consumer_key),
        "consumer_secret": encrypt_text(payload.consumer_secret),
        "consumer_key_hint": key_hint(payload.consumer_key),
        "rest_api_mode": existing_value.get("rest_api_mode"),
    }
    for sync_key in WOOCOMMERCE_LAST_SYNC_KEYS.values():
        if existing_value.get(sync_key):
            encrypted_value[sync_key] = existing_value[sync_key]
    for status_key in (
        "video_plugin_detected",
        "video_plugin_compatible",
        "video_plugin_version",
        "wordpress_max_upload_bytes",
        "video_plugin_checked",
    ):
        if status_key in existing_value:
            encrypted_value[status_key] = existing_value[status_key]
    wordpress_username = (payload.wordpress_username or "").strip()
    wordpress_application_password = (payload.wordpress_application_password or "").strip()
    webhook_secret = (payload.webhook_secret or "").strip()
    if webhook_secret:
        encrypted_value["webhook_secret"] = encrypt_text(webhook_secret)
        encrypted_value["webhook_secret_configured"] = True
    elif existing_value.get("webhook_secret"):
        encrypted_value["webhook_secret"] = existing_value["webhook_secret"]
        encrypted_value["webhook_secret_configured"] = bool(
            existing_value.get("webhook_secret_configured", True)
        )
    if wordpress_username:
        encrypted_value["wordpress_username"] = encrypt_text(wordpress_username)
        encrypted_value["wordpress_username_hint"] = wordpress_username
    elif existing_value.get("wordpress_username"):
        encrypted_value["wordpress_username"] = existing_value["wordpress_username"]
        encrypted_value["wordpress_username_hint"] = existing_value.get("wordpress_username_hint")
    if wordpress_application_password:
        encrypted_value["wordpress_application_password"] = encrypt_text(
            wordpress_application_password
        )
    elif existing_value.get("wordpress_application_password"):
        encrypted_value["wordpress_application_password"] = existing_value[
            "wordpress_application_password"
        ]
    if setting is None:
        setting = Setting(
            company_id=scoped_company_id,
            key=WOOCOMMERCE_SETTING_KEY,
            value=encrypted_value,
        )
        db.add(setting)
    else:
        setting.value = encrypted_value
    db.flush()
    db.refresh(setting)
    record_audit(
        db,
        action="woocommerce.configured",
        company_id=scoped_company_id,
        user_id=user_id,
        entity_type="setting",
        entity_id=WOOCOMMERCE_SETTING_KEY,
        metadata={"site_url_configured": True},
    )
    return setting


def load_woocommerce_config(db: Session, company_id: str | None) -> WooCommerceConfig | None:
    scoped_company_id = require_company_id(company_id)
    setting = get_setting(db, scoped_company_id, WOOCOMMERCE_SETTING_KEY)
    if setting is None:
        return None
    value = setting.value
    try:
        site_url = normalize_site_url(decrypt_text(str(value["site_url"])))
        consumer_key = decrypt_text(str(value["consumer_key"]))
        consumer_secret = decrypt_text(str(value["consumer_secret"]))
    except Exception as exc:
        raise ServiceError(500, "WooCommerce credentials could not be decrypted.") from exc
    wordpress_username = None
    wordpress_application_password = None
    webhook_secret = None
    if value.get("webhook_secret"):
        try:
            webhook_secret = decrypt_text(str(value["webhook_secret"]))
        except Exception as exc:
            raise ServiceError(500, "WooCommerce webhook secret could not be decrypted.") from exc
    if value.get("wordpress_username"):
        try:
            wordpress_username = decrypt_text(str(value["wordpress_username"]))
        except Exception as exc:
            raise ServiceError(500, "WordPress media username could not be decrypted.") from exc
    if value.get("wordpress_application_password"):
        try:
            wordpress_application_password = decrypt_text(
                str(value["wordpress_application_password"])
            )
        except Exception as exc:
            raise ServiceError(
                500,
                "WordPress media application password could not be decrypted.",
            ) from exc
    return WooCommerceConfig(
        site_url=site_url,
        consumer_key=consumer_key,
        consumer_secret=consumer_secret,
        key_hint=str(value.get("consumer_key_hint") or key_hint(consumer_key)),
        rest_api_mode=normalize_rest_api_mode(value.get("rest_api_mode")),
        wordpress_username=wordpress_username,
        wordpress_application_password=wordpress_application_password,
        webhook_secret=webhook_secret,
    )


def test_woocommerce_connection(
    db: Session,
    company_id: str | None,
    *,
    timeout: float = 5.0,
) -> ConnectionTestResult:
    config = load_woocommerce_config(db, company_id)
    if config is None:
        raise ServiceError(404, "WooCommerce is not configured.")

    checked: list[str] = []
    for resource_path, label in WOOCOMMERCE_SYNC_READ_ENDPOINTS:
        try:
            result = make_woocommerce_request(
                db,
                company_id,
                "GET",
                resource_path,
                params={"per_page": 1},
                timeout=timeout,
            )
        except ServiceError as exc:
            return ConnectionTestResult(
                ok=False,
                status="network_error" if exc.status_code == 503 else "http_error",
                detail=str(exc),
            )

        response = result.response
        if response.status_code in {401, 403}:
            return ConnectionTestResult(
                ok=False,
                status="auth_failed",
                detail=format_remote_http_error(action="WooCommerce authentication", result=result),
            )
        if response.status_code >= 400:
            return ConnectionTestResult(
                ok=False,
                status="http_error",
                detail=format_remote_http_error(action="WooCommerce connection", result=result),
            )
        checked.append(label)

    plugin_status = test_wordpress_video_plugin(db, company_id, timeout=timeout)
    detail = f"WooCommerce connection succeeded. Read access verified for {', '.join(checked)}."
    if plugin_status["compatible"]:
        detail += f" ChoiceOye video plugin {plugin_status['version']} detected."
    elif plugin_status["detected"]:
        detail += (
            " ChoiceOye video plugin was detected but is incompatible or WooCommerce "
            "is unavailable; video metadata can sync but will not render."
        )
    else:
        detail += (
            " ChoiceOye video plugin was not detected; video metadata can sync but "
            "will not render."
        )
    return ConnectionTestResult(
        ok=True,
        status="ok",
        detail=detail,
        video_plugin_detected=bool(plugin_status["detected"]),
        video_plugin_compatible=bool(plugin_status["compatible"]),
        video_plugin_version=(
            str(plugin_status["version"]) if plugin_status.get("version") else None
        ),
        wordpress_max_upload_bytes=(
            int(plugin_status["max_upload_bytes"])
            if plugin_status.get("max_upload_bytes") is not None
            else None
        ),
    )


def saved_wordpress_video_plugin_status(
    db: Session, company_id: str | None
) -> dict[str, object]:
    if company_id is None:
        return {
            "detected": False,
            "compatible": False,
            "version": None,
            "max_upload_bytes": None,
            "checked": False,
        }
    setting = get_setting(db, require_company_id(company_id), WOOCOMMERCE_SETTING_KEY)
    value = setting.value if setting is not None else {}
    return {
        "detected": bool(value.get("video_plugin_detected", False)),
        "compatible": bool(value.get("video_plugin_compatible", False)),
        "version": value.get("video_plugin_version"),
        "max_upload_bytes": value.get("wordpress_max_upload_bytes"),
        "checked": bool(value.get("video_plugin_checked", False)),
    }


def test_wordpress_video_plugin(
    db: Session,
    company_id: str | None,
    *,
    timeout: float = 5.0,
) -> dict[str, object]:
    scoped_company_id = require_company_id(company_id)
    config = load_woocommerce_config(db, scoped_company_id)
    if config is None:
        raise ServiceError(404, "WooCommerce is not configured.")
    detected = False
    compatible = False
    version: str | None = None
    max_upload_bytes: int | None = None
    for rest_api_mode in woocommerce_rest_mode_candidates(config.rest_api_mode):
        url = build_wordpress_namespace_url(
            config.site_url,
            "choiceoye-erp/v1/status",
            rest_api_mode,
        )
        try:
            response = _remote_request_with_retry(
                "GET", url, timeout=timeout, follow_redirects=True
            )
        except Exception as exc:
            LOGGER.info("ChoiceOye video plugin status probe failed: %s", exc)
            continue
        if response.status_code != 200:
            continue
        try:
            payload = response.json()
        except ValueError:
            continue
        if not isinstance(payload, dict):
            continue
        detected = payload.get("plugin") == "choiceoye-erp-product-videos"
        supported = payload.get("schema_versions")
        compatible = (
            detected
            and payload.get("woocommerce") is True
            and isinstance(supported, list)
            and WOOCOMMERCE_VIDEO_SCHEMA_VERSION in supported
        )
        if payload.get("version") is not None:
            version = str(payload["version"])
        try:
            max_upload_bytes = max(int(payload.get("max_upload_bytes") or 0), 0) or None
        except (TypeError, ValueError):
            max_upload_bytes = None
        break

    setting = get_setting(db, scoped_company_id, WOOCOMMERCE_SETTING_KEY)
    if setting is not None:
        value = dict(setting.value)
        value.update(
            {
                "video_plugin_detected": detected,
                "video_plugin_compatible": compatible,
                "video_plugin_version": version,
                "wordpress_max_upload_bytes": max_upload_bytes,
                "video_plugin_checked": True,
            }
        )
        setting.value = value
        db.flush()
    return {
        "detected": detected,
        "compatible": compatible,
        "version": version,
        "max_upload_bytes": max_upload_bytes,
    }


def validate_resource_type(resource_type: str) -> str:
    normalized = resource_type.strip().lower()
    if normalized not in ALLOWED_RESOURCE_TYPES:
        raise ServiceError(422, f"Unsupported WooCommerce resource type: {resource_type}.")
    return normalized


def upsert_external_resource_map(
    db: Session,
    *,
    company_id: str | None,
    resource_type: str,
    internal_id: str,
    external_id: str,
    version: str | None = None,
    metadata: dict[str, object] | None = None,
) -> ExternalResourceMap:
    scoped_company_id = require_company_id(company_id)
    normalized_type = validate_resource_type(resource_type)
    mapping = db.scalar(
        select(ExternalResourceMap).where(
            ExternalResourceMap.company_id == scoped_company_id,
            ExternalResourceMap.connector == CONNECTOR,
            ExternalResourceMap.external_resource_type == normalized_type,
            ExternalResourceMap.external_resource_id == external_id,
        )
    )
    if mapping is None:
        mapping = ExternalResourceMap(
            company_id=scoped_company_id,
            connector=CONNECTOR,
            internal_resource_type=normalized_type,
            internal_resource_id=internal_id,
            external_resource_type=normalized_type,
            external_resource_id=external_id,
            version=version,
            metadata_json=metadata or {},
        )
        db.add(mapping)
    else:
        mapping.internal_resource_type = normalized_type
        mapping.internal_resource_id = internal_id
        mapping.version = version
        mapping.metadata_json = metadata or {}
    db.flush()
    db.refresh(mapping)
    return mapping


def get_external_resource_map(
    db: Session,
    *,
    company_id: str | None,
    resource_type: str,
    external_id: str,
) -> ExternalResourceMap | None:
    scoped_company_id = require_company_id(company_id)
    normalized_type = validate_resource_type(resource_type)
    return db.scalar(
        select(ExternalResourceMap).where(
            ExternalResourceMap.company_id == scoped_company_id,
            ExternalResourceMap.connector == CONNECTOR,
            ExternalResourceMap.external_resource_type == normalized_type,
            ExternalResourceMap.external_resource_id == external_id,
        )
    )


def enqueue_sync_outbox(
    db: Session,
    *,
    company_id: str | None,
    operation: str,
    resource_type: str,
    resource_id: str,
    payload: dict[str, object],
    idempotency_key: str | None = None,
) -> SyncOutbox:
    scoped_company_id = require_company_id(company_id)
    normalized_type = validate_resource_type(resource_type)
    key = idempotency_key or (
        f"{CONNECTOR}:{scoped_company_id}:{operation}:{normalized_type}:{resource_id}:{new_uuid()}"
    )
    existing = db.scalar(select(SyncOutbox).where(SyncOutbox.idempotency_key == key))
    if existing is not None:
        if existing.status == "failed":
            existing.status = "pending"
            existing.attempts = 0
            existing.next_attempt_at = None
            existing.last_error = None
            existing.payload = payload
            db.flush()
        elif (
            existing.operation in {"push_media", "push_videos"}
            and existing.status == "pending"
            and existing.last_error
            in {
                "Waiting for WooCommerce product sync before media sync.",
                "Waiting for WooCommerce product sync before video sync.",
            }
        ):
            # A deferred media job did not make a remote request. Reset its
            # attempt counter when the product is queued again so a later
            # product mapping can release the upload.
            existing.attempts = 0
            existing.next_attempt_at = None
            db.flush()
        return existing
    outbox = SyncOutbox(
        company_id=scoped_company_id,
        connector=CONNECTOR,
        operation=operation,
        resource_type=normalized_type,
        resource_id=resource_id,
        payload=payload,
        idempotency_key=key,
        status="pending",
    )
    db.add(outbox)
    db.flush()
    db.refresh(outbox)
    return outbox


def _woocommerce_product_status(product_status: str | None) -> tuple[str, str]:
    normalized = str(product_status or "draft").strip().lower()
    if normalized == "active":
        return "publish", "visible"
    return "draft", "hidden"


def _minor_to_price_string(amount_minor: int | None) -> str:
    normalized_minor = max(int(amount_minor or 0), 0)
    return f"{normalized_minor / 100:.2f}"


def _price_string_to_minor(value: object) -> int:
    try:
        return max(int(float(value or 0) * 100), 0)
    except (TypeError, ValueError):
        return 0


def _local_media_path(media_url: str) -> Path | None:
    parsed_path = urlparse(media_url).path
    if not parsed_path.startswith("/media/"):
        return None
    relative = parsed_path.removeprefix("/media/").lstrip("/")
    if not relative:
        return None
    upload_root = Path(get_settings().media_upload_dir).resolve()
    candidate = (upload_root / Path(relative)).resolve()
    try:
        candidate.relative_to(upload_root)
    except ValueError as exc:
        raise ServiceError(
            422,
            "Product media path is outside the media upload directory.",
        ) from exc
    return candidate


def _wordpress_media_headers(filename: str, content_type: str) -> dict[str, str]:
    safe_filename = filename.replace('"', "")
    return {
        "Content-Disposition": f'attachment; filename="{safe_filename}"',
        "Content-Type": content_type,
    }


def upload_product_image_to_wordpress(
    db: Session,
    *,
    company_id: str,
    image: ProductImage,
    checkpoint: Callable[[], None] | None = None,
) -> None:
    local_path = _local_media_path(image.url)
    if local_path is None or _woocommerce_image_id(image.external_id) is not None:
        return
    if not local_path.exists() or not local_path.is_file():
        raise ServiceError(
            422,
            f"Product image file is missing locally and cannot be uploaded: {image.url}",
        )

    config = load_woocommerce_config(db, company_id)
    if config is None:
        raise ServiceError(404, "WooCommerce is not configured.")
    if not config.wordpress_username or not config.wordpress_application_password:
        raise ServiceError(
            422,
            "WordPress media username and application password are required to upload local "
            "ERP product images to WordPress.",
        )

    filename = image.name or local_path.name
    content_type = (
        mimetypes.guess_type(filename)[0]
        or mimetypes.guess_type(str(local_path))[0]
        or "application/octet-stream"
    )
    headers = _wordpress_media_headers(filename, content_type)
    auth = (config.wordpress_username, config.wordpress_application_password)
    data = local_path.read_bytes()
    last_result: WooCommerceRequestResult | None = None
    for rest_api_mode in woocommerce_rest_mode_candidates(config.rest_api_mode):
        url = build_wordpress_request_url(config.site_url, "/media", rest_api_mode)
        try:
            response = _remote_request_with_retry(
                "POST",
                url,
                auth=auth,
                content=data,
                headers=headers,
                timeout=30.0,
                follow_redirects=True,
            )
        except httpx.RequestError as exc:
            raise ServiceError(
                503,
                f"WordPress media upload failed for {filename}: {exc}",
            ) from exc
        result = WooCommerceRequestResult(
            response=response,
            rest_api_mode=rest_api_mode,
            auth_mode="wordpress_application_password",
            resource_path="/wp/v2/media",
            url=url,
        )
        if response.status_code in {200, 201}:
            payload = response.json()
            media_id = payload.get("id") if isinstance(payload, dict) else None
            if media_id is None:
                raise ServiceError(
                    502,
                    "WordPress media upload succeeded but did not return a media ID.",
                )
            image.external_id = str(media_id)
            source_url = payload.get("source_url") if isinstance(payload, dict) else None
            if isinstance(source_url, str) and source_url.strip():
                image.url = source_url.strip()
            # Persist the WordPress media ID before attaching it to WooCommerce.
            # If a worker dies after upload, recovery can attach this existing
            # media item instead of uploading a duplicate on the next attempt.
            db.flush()
            if checkpoint is not None:
                checkpoint()
            return
        last_result = result

    if last_result is None:
        raise ServiceError(502, "WordPress media upload was not attempted.")
    raise ServiceError(
        502,
        format_remote_http_error(action="Upload product image", result=last_result),
    )


def upload_local_product_images_to_wordpress(
    db: Session,
    *,
    company_id: str,
    product: Product,
    checkpoint: Callable[[], None] | None = None,
) -> None:
    images = db.scalars(
        select(ProductImage).where(
            ProductImage.company_id == company_id,
            ProductImage.product_id == product.id,
        )
    ).all()
    for image in images:
        upload_product_image_to_wordpress(
            db,
            company_id=company_id,
            image=image,
            checkpoint=checkpoint,
        )


def upload_product_video_to_wordpress(
    db: Session,
    *,
    company_id: str,
    video: ProductVideo,
    checkpoint: Callable[[], None] | None = None,
) -> None:
    if video.source_type != "uploaded" or (video.external_id and video.remote_url):
        return
    local_path = _local_media_path(video.url)
    if local_path is None or not local_path.exists() or not local_path.is_file():
        raise ServiceError(
            422,
            f"Product video file is missing locally and cannot be uploaded: {video.url}",
        )
    config = load_woocommerce_config(db, company_id)
    if config is None:
        raise ServiceError(404, "WooCommerce is not configured.")
    if not config.wordpress_username or not config.wordpress_application_password:
        raise ServiceError(
            422,
            "WordPress media username and application password are required to upload local "
            "ERP product videos.",
        )
    file_size = local_path.stat().st_size
    plugin_status = saved_wordpress_video_plugin_status(db, company_id)
    if not plugin_status["checked"]:
        # Ask once before a local upload so the operator gets a useful limit
        # error instead of WordPress rejecting the streamed body later.
        plugin_status = test_wordpress_video_plugin(db, company_id)
    remote_limit = plugin_status.get("max_upload_bytes")
    if remote_limit is not None and file_size > int(remote_limit):
        remote_limit_bytes = int(remote_limit)
        remote_limit_label = (
            f"{remote_limit_bytes // (1024 * 1024)} MB"
            if remote_limit_bytes >= 1024 * 1024
            else f"{remote_limit_bytes} bytes"
        )
        raise ServiceError(
            413,
            "Product video exceeds the WordPress upload limit "
            f"({remote_limit_label}).",
        )

    filename = video.name or local_path.name
    headers = _wordpress_media_headers(filename, "video/mp4")
    headers["Content-Length"] = str(file_size)
    auth = (config.wordpress_username, config.wordpress_application_password)
    last_result: WooCommerceRequestResult | None = None
    for rest_api_mode in woocommerce_rest_mode_candidates(config.rest_api_mode):
        url = build_wordpress_request_url(config.site_url, "/media", rest_api_mode)
        try:
            response = _remote_request_with_retry(
                "POST",
                url,
                auth=auth,
                content=ReusableFileBody(local_path),
                headers=headers,
                timeout=120.0,
                follow_redirects=True,
            )
        except httpx.RequestError as exc:
            raise ServiceError(
                503,
                f"WordPress media upload failed for {filename}: {exc}",
            ) from exc
        result = WooCommerceRequestResult(
            response=response,
            rest_api_mode=rest_api_mode,
            auth_mode="wordpress_application_password",
            resource_path="/wp/v2/media",
            url=url,
        )
        if response.status_code in {200, 201}:
            payload = response.json()
            media_id = payload.get("id") if isinstance(payload, dict) else None
            source_url = payload.get("source_url") if isinstance(payload, dict) else None
            if media_id is None or not isinstance(source_url, str) or not source_url.strip():
                raise ServiceError(
                    502,
                    "WordPress video upload succeeded but did not return a media ID and URL.",
                )
            if urlparse(source_url).scheme.lower() != "https":
                raise ServiceError(
                    422,
                    "WordPress returned a non-HTTPS product video URL. Configure the WordPress "
                    "site URL and uploads to use HTTPS before syncing product videos.",
                )
            video.external_id = str(media_id)
            video.remote_url = source_url.strip()
            video.sync_status = "pending_update"
            db.flush()
            if checkpoint is not None:
                checkpoint()
            return
        last_result = result
    if last_result is None:
        raise ServiceError(502, "WordPress video upload was not attempted.")
    raise ServiceError(
        502,
        format_remote_http_error(action="Upload product video", result=last_result),
    )


def build_woocommerce_product_video_manifest(
    db: Session,
    *,
    company_id: str,
    product: Product,
    checkpoint: Callable[[], None] | None = None,
) -> dict[str, object]:
    rows = product_videos(db, product.id)
    videos: list[dict[str, object]] = []
    for index, video in enumerate(rows):
        upload_product_video_to_wordpress(
            db,
            company_id=company_id,
            video=video,
            checkpoint=checkpoint,
        )
        public_url = video.remote_url if video.source_type == "uploaded" else video.url
        if not public_url:
            raise ServiceError(422, f"Product video {video.id} has no public URL.")
        item: dict[str, object] = {
            "erp_video_id": video.id,
            "source_type": video.source_type,
            "url": public_url,
            "name": video.name or "",
            "sort_order": index,
        }
        if video.external_id:
            try:
                item["attachment_id"] = int(video.external_id)
            except ValueError:
                item["attachment_id"] = video.external_id
        videos.append(item)
    return {"schema_version": WOOCOMMERCE_VIDEO_SCHEMA_VERSION, "videos": videos}


def product_images_for_sync(
    db: Session,
    *,
    company_id: str,
    product_id: str,
    include_pending_removals: bool = False,
) -> list[ProductImage]:
    query = (
        select(ProductImage)
        .where(
            ProductImage.company_id == company_id,
            ProductImage.product_id == product_id,
        )
        .order_by(ProductImage.sort_order, ProductImage.created_at, ProductImage.id)
    )
    if not include_pending_removals:
        query = query.where(ProductImage.sync_status != "pending_remove")
    return list(db.scalars(query).all())


def _woocommerce_image_payload(image: ProductImage, product_name: str) -> dict[str, object] | None:
    payload: dict[str, object] = {
        "alt": image.alt_text or product_name,
    }
    if image.name:
        payload["name"] = image.name
    if image.external_id:
        remote_id = _woocommerce_image_id(image.external_id)
        if remote_id is not None:
            payload["id"] = remote_id
            return payload
        # Legacy/demo rows sometimes contain a non-WooCommerce placeholder ID.
        # Do not send that value as an image ID or as an unreachable source URL.
        return None
    if image.url.lower().startswith(("http://", "https://")):
        payload["src"] = image.url
        return payload
    return None


def _woocommerce_image_id(value: object) -> int | None:
    if value is None:
        return None
    try:
        parsed = int(str(value))
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _product_image_requires_sync(image: ProductImage) -> bool:
    if image.sync_status == "pending_remove":
        return False
    if image.sync_status != "synced":
        return True
    if image.external_id:
        return (
            _woocommerce_image_id(image.external_id) is None
            and _local_media_path(image.url) is not None
        )
    return True


def _parse_woo_stock_quantity(item: dict) -> int | None:
    raw_quantity = item.get("stock_quantity")
    if raw_quantity in {None, ""}:
        return None
    try:
        return max(int(float(raw_quantity)), 0)
    except (TypeError, ValueError):
        return None


def ensure_woocommerce_warehouse(db: Session, company_id: str) -> Warehouse:
    warehouse = db.scalar(
        select(Warehouse).where(
            Warehouse.company_id == company_id,
            Warehouse.code == "WOO",
        )
    )
    if warehouse is not None:
        if not warehouse.is_active:
            warehouse.is_active = True
        return warehouse
    warehouse = Warehouse(
        company_id=company_id,
        code="WOO",
        name="WooCommerce",
        is_active=True,
    )
    db.add(warehouse)
    db.flush()
    db.refresh(warehouse)
    return warehouse


def sync_product_stock_from_woocommerce(
    db: Session,
    *,
    company_id: str,
    product: Product,
    item: dict,
) -> None:
    # A vendor's local shop ledger is the authoritative shared balance. Pulling
    # the remote product quantity here would overwrite POS/purchase movements
    # and make an online order appear to use a second warehouse balance.
    vendor_ids = {
        value
        for value in [product.vendor_id]
        if value
    }
    vendor_ids.update(
        db.scalars(
            select(VendorProduct.vendor_id).where(
                VendorProduct.company_id == company_id,
                VendorProduct.product_id == product.id,
            )
        ).all()
    )
    if vendor_ids:
        return
    target_quantity = _parse_woo_stock_quantity(item)
    if target_quantity is None:
        return

    sku = str(item.get("sku") or "").strip()
    variant = None
    if sku:
        variant = db.scalar(
            select(ProductVariant).where(
                ProductVariant.company_id == company_id,
                ProductVariant.product_id == product.id,
                ProductVariant.sku == sku,
            )
        )
    if variant is None:
        variant = db.scalar(
            select(ProductVariant)
            .where(
                ProductVariant.company_id == company_id,
                ProductVariant.product_id == product.id,
                ProductVariant.is_active.is_(True),
            )
            .order_by(ProductVariant.created_at)
        )

    warehouse = ensure_woocommerce_warehouse(db, company_id)
    from erp.packages.core.inventory_services import current_stock

    current_quantity = current_stock(
        db,
        company_id=company_id,
        warehouse_id=warehouse.id,
        product_id=product.id,
        variant_id=variant.id if variant is not None else None,
    )
    delta = target_quantity - current_quantity
    if delta == 0:
        return

    db.add(
        StockMovement(
            company_id=company_id,
            warehouse_id=warehouse.id,
            product_id=product.id,
            variant_id=variant.id if variant is not None else None,
            movement_type="adjustment",
            quantity_delta=delta,
            reference_type="woocommerce_product",
            reference_id=str(item.get("id")),
            reason="WooCommerce stock sync",
            metadata_json={
                "source": "woocommerce",
                "external_product_id": str(item.get("id")),
                "stock_status": item.get("stock_status"),
            },
            created_by_id=woocommerce_sync_user_id(db, company_id),
        )
    )


def _taxonomy_mapping(
    db: Session, *, company_id: str, resource_type: str, internal_id: str
) -> ExternalResourceMap | None:
    return db.scalar(
        select(ExternalResourceMap).where(
            ExternalResourceMap.company_id == company_id,
            ExternalResourceMap.connector == CONNECTOR,
            ExternalResourceMap.internal_resource_type == resource_type,
            ExternalResourceMap.internal_resource_id == internal_id,
        )
    )


def _remote_taxonomy_id(result: WooCommerceRequestResult) -> str | None:
    try:
        payload = result.response.json()
    except ValueError:
        return None
    if not isinstance(payload, dict):
        return None
    if payload.get("id") is not None:
        return str(payload["id"])
    if payload.get("code") == "term_exists":
        data = payload.get("data")
        if isinstance(data, dict) and data.get("resource_id") is not None:
            return str(data["resource_id"])
    return None


def _find_remote_taxonomy(
    db: Session,
    *,
    company_id: str,
    resource_path: str,
    slug: str,
) -> str | None:
    result = make_woocommerce_request(
        db,
        company_id,
        "GET",
        resource_path,
        params={"slug": slug},
    )
    if result.response.status_code == 404:
        return None
    if result.response.status_code != 200:
        raise ServiceError(
            502,
            format_remote_http_error(action="Find WooCommerce taxonomy", result=result),
        )
    payload = result.response.json()
    if not isinstance(payload, list):
        raise ServiceError(502, "WooCommerce taxonomy lookup returned an invalid payload.")
    for item in payload:
        if isinstance(item, dict) and item.get("id") is not None:
            return str(item["id"])
    return None


def _sync_remote_taxonomy_term(
    db: Session,
    *,
    company_id: str,
    resource_type: str,
    resource_path: str,
    internal_id: str,
    name: str,
    slug: str,
    description: str,
    parent_id: int | None = None,
) -> str:
    mapping = _taxonomy_mapping(
        db,
        company_id=company_id,
        resource_type=resource_type,
        internal_id=internal_id,
    )
    payload: dict[str, object] = {
        "name": name,
        "slug": slug,
        "description": description,
    }
    if parent_id is not None:
        payload["parent"] = parent_id

    remote_id = mapping.external_resource_id if mapping is not None else None
    if remote_id is not None:
        result = make_woocommerce_request(
            db,
            company_id,
            "PUT",
            f"{resource_path}/{remote_id}",
            payload,
        )
        if result.response.status_code in {200, 201}:
            return remote_id
        if result.response.status_code != 404:
            raise ServiceError(
                502,
                format_remote_http_error(
                    action=f"Update WooCommerce {resource_type}",
                    result=result,
                ),
            )
        db.delete(mapping)
        db.flush()

    remote_id = _find_remote_taxonomy(
        db,
        company_id=company_id,
        resource_path=resource_path,
        slug=slug,
    )
    if remote_id is None:
        result = make_woocommerce_request(
            db,
            company_id,
            "POST",
            resource_path,
            payload,
        )
        if result.response.status_code not in {200, 201}:
            remote_id = _remote_taxonomy_id(result)
            if remote_id is None:
                raise ServiceError(
                    502,
                    format_remote_http_error(
                        action=f"Create WooCommerce {resource_type}", result=result
                    ),
                )
        else:
            remote_id = _remote_taxonomy_id(result)
            if remote_id is None:
                raise ServiceError(
                    502,
                    f"WooCommerce {resource_type} creation returned an invalid payload.",
                )

    upsert_external_resource_map(
        db,
        company_id=company_id,
        resource_type=resource_type,
        internal_id=internal_id,
        external_id=remote_id,
    )
    # A term found by slug or returned through term_exists may have stale
    # display data, so apply the ERP values after resolving its ID.
    result = make_woocommerce_request(
        db,
        company_id,
        "PUT",
        f"{resource_path}/{remote_id}",
        payload,
    )
    if result.response.status_code not in {200, 201}:
        raise ServiceError(
            502,
            format_remote_http_error(action=f"Update WooCommerce {resource_type}", result=result),
        )
    return remote_id


def ensure_remote_category(db: Session, *, company_id: str, category: Category) -> str:
    """Resolve, create, and update a WooCommerce category."""
    parent_id = None
    if category.parent_id:
        parent = db.scalar(
            select(Category).where(
                Category.company_id == company_id,
                Category.id == category.parent_id,
            )
        )
        if parent is not None:
            parent_id = int(
                ensure_remote_category(db, company_id=company_id, category=parent)
            )
    return _sync_remote_taxonomy_term(
        db,
        company_id=company_id,
        resource_type="category",
        internal_id=category.id,
        resource_path="/products/categories",
        name=category.name,
        slug=category.slug,
        description=category.description or "",
        parent_id=parent_id,
    )


def ensure_remote_brand(db: Session, *, company_id: str, brand: Brand) -> str:
    """Resolve, create, and update a WooCommerce brand term."""
    return _sync_remote_taxonomy_term(
        db,
        company_id=company_id,
        resource_type="brand",
        internal_id=brand.id,
        resource_path="/products/brands",
        name=brand.name,
        slug=brand.slug,
        description=brand.description or "",
    )


def _product_category_ids(db: Session, *, company_id: str, product: Product) -> list[str]:
    category_ids = list(
        db.scalars(
            select(ProductCategoryLink.category_id)
            .where(
                ProductCategoryLink.company_id == company_id,
                ProductCategoryLink.product_id == product.id,
            )
            .order_by(ProductCategoryLink.sort_order)
        ).all()
    )
    if not category_ids and product.category_id:
        category_ids = [product.category_id]
    return list(dict.fromkeys(category_ids))


def sync_product_taxonomies(
    db: Session,
    *,
    company_id: str,
    product: Product,
) -> dict[str, int]:
    """Ensure one product's category and brand mappings exist remotely."""
    categories = 0
    for category_id in _product_category_ids(db, company_id=company_id, product=product):
        category = db.scalar(
            select(Category).where(
                Category.company_id == company_id,
                Category.id == category_id,
            )
        )
        if category is not None:
            ensure_remote_category(db, company_id=company_id, category=category)
            categories += 1
    brands = 0
    if product.brand_id:
        brand = db.scalar(
            select(Brand).where(
                Brand.company_id == company_id,
                Brand.id == product.brand_id,
            )
        )
        if brand is not None:
            ensure_remote_brand(db, company_id=company_id, brand=brand)
            brands = 1
    return {"categories": categories, "brands": brands}


def sync_local_taxonomies_for_sync(
    db: Session,
    company_id: str,
    *,
    vendor_id: str | None = None,
    product_ids: set[str] | None = None,
) -> dict[str, object]:
    """Publish all local terms referenced by the scoped product catalog."""
    products = db.scalars(
        select(Product).where(Product.company_id == company_id).order_by(Product.created_at)
    ).all()
    category_ids: set[str] = set()
    brand_ids: set[str] = set()
    for product in products:
        if product_ids is not None and product.id not in product_ids:
            continue
        if vendor_id and not product_belongs_to_vendor(
            db,
            company_id=company_id,
            product=product,
            vendor_id=vendor_id,
        ):
            continue
        category_ids.update(_product_category_ids(db, company_id=company_id, product=product))
        if product.brand_id:
            brand_ids.add(product.brand_id)

    synced_categories = 0
    synced_brands = 0
    errors: list[str] = []
    categories = db.scalars(
        select(Category).where(
            Category.company_id == company_id,
            Category.id.in_(category_ids),
        )
    ).all() if category_ids else []
    for category in sorted(categories, key=lambda item: (item.name, item.id)):
        try:
            ensure_remote_category(db, company_id=company_id, category=category)
            synced_categories += 1
        except WooCommerceRateLimitError:
            raise
        except Exception as exc:
            errors.append(f"Category '{category.name}': {exc}")

    brands = db.scalars(
        select(Brand).where(
            Brand.company_id == company_id,
            Brand.id.in_(brand_ids),
        )
    ).all() if brand_ids else []
    for brand in sorted(brands, key=lambda item: (item.name, item.id)):
        try:
            ensure_remote_brand(db, company_id=company_id, brand=brand)
            synced_brands += 1
        except WooCommerceRateLimitError:
            raise
        except Exception as exc:
            errors.append(f"Brand '{brand.name}': {exc}")

    return {
        "synced_categories": synced_categories,
        "synced_brands": synced_brands,
        "failed_taxonomies": len(errors),
        "taxonomy_errors": errors,
    }


def pending_product_outbox_ids(db: Session, company_id: str) -> set[str]:
    """Product records whose queued payload may need taxonomy mappings."""

    now = utcnow()
    return {
        str(product_id)
        for product_id in db.scalars(
            select(SyncOutbox.resource_id).where(
                SyncOutbox.company_id == company_id,
                SyncOutbox.connector == CONNECTOR,
                SyncOutbox.resource_type == "product",
                SyncOutbox.operation == "push",
                SyncOutbox.status.in_({"pending", "failed"}),
                SyncOutbox.attempts < SYNC_OUTBOX_MAX_ATTEMPTS,
                (SyncOutbox.next_attempt_at.is_(None)) | (SyncOutbox.next_attempt_at <= now),
            )
        ).all()
        if product_id
    }


def product_taxonomy_payload(
    db: Session,
    *,
    company_id: str,
    product: Product,
    require_mappings: bool = True,
) -> dict[str, object]:
    categories: list[dict[str, int]] = []
    for category_id in _product_category_ids(db, company_id=company_id, product=product):
        mapping = _taxonomy_mapping(
            db,
            company_id=company_id,
            resource_type="category",
            internal_id=category_id,
        )
        if mapping is None:
            if require_mappings:
                raise ServiceError(409, f"Category {category_id} has not been synchronized.")
            continue
        categories.append({"id": int(mapping.external_resource_id)})
    payload: dict[str, object] = {"categories": categories}
    if product.brand_id:
        mapping = _taxonomy_mapping(
            db,
            company_id=company_id,
            resource_type="brand",
            internal_id=product.brand_id,
        )
        if mapping is None:
            if require_mappings:
                raise ServiceError(409, f"Brand {product.brand_id} has not been synchronized.")
            return payload
        payload["brands"] = [{"id": int(mapping.external_resource_id)}]
    return payload


def build_woocommerce_product_payload(
    db: Session,
    product: Product,
    *,
    require_taxonomy_mappings: bool = True,
) -> dict[str, object]:
    variant = db.scalar(
        select(ProductVariant)
        .where(
            ProductVariant.company_id == product.company_id,
            ProductVariant.product_id == product.id,
            ProductVariant.is_active.is_(True),
        )
        .order_by(ProductVariant.created_at)
    )
    vendor_id = product.vendor_id
    if vendor_id is None:
        vendor_product = db.scalar(
            select(VendorProduct.vendor_id).where(
                VendorProduct.company_id == product.company_id,
                VendorProduct.product_id == product.id,
            )
        )
        if vendor_product is not None:
            vendor_id = str(vendor_product)

    woo_status, default_visibility = _woocommerce_product_status(product.status)
    listing = db.scalar(
        select(ProductChannelListing).where(
            ProductChannelListing.company_id == product.company_id,
            ProductChannelListing.product_id == product.id,
            ProductChannelListing.channel == CONNECTOR,
        )
    )
    if listing is not None and listing.listing_status != "published":
        woo_status, default_visibility = "draft", "hidden"
    catalog_visibility = product.visibility if woo_status == "publish" else default_visibility
    sku = product.sku or (variant.sku if variant and variant.sku else "")
    regular_price_minor = product.regular_price_minor or (variant.price_minor if variant else 0)
    sale_price_minor = product.sale_price_minor
    payload: dict[str, object] = {
        "name": product.name,
        "slug": product.slug,
        "sku": sku,
        "type": product.product_type,
        "status": woo_status,
        "catalog_visibility": catalog_visibility,
        "featured": product.featured,
        "regular_price": _minor_to_price_string(regular_price_minor),
        "manage_stock": product.manage_stock,
        "stock_quantity": product.stock_quantity,
        "stock_status": product.stock_status,
        "backorders": product.backorders,
        "sold_individually": product.sold_individually,
        "description": product.description or "",
        "short_description": product.short_description or product.seo_description or "",
        "tax_status": product.tax_status,
        "tax_class": product.tax_class or "",
        "weight": product.weight or "",
        "dimensions": {
            "length": product.length or "",
            "width": product.width or "",
            "height": product.height or "",
        },
        "shipping_class": product.shipping_class or "",
        "reviews_allowed": product.reviews_allowed,
        "purchase_note": product.purchase_note or "",
        "menu_order": product.menu_order,
        "attributes": product.attributes,
        "default_attributes": product.default_attributes,
        "meta_data": [],
    }
    if sale_price_minor is not None:
        payload["sale_price"] = _minor_to_price_string(sale_price_minor)
    if product.sale_start_at is not None:
        payload["date_on_sale_from"] = product.sale_start_at.isoformat()
    if product.sale_end_at is not None:
        payload["date_on_sale_to"] = product.sale_end_at.isoformat()
    if product.global_unique_id:
        payload["global_unique_id"] = product.global_unique_id
    if vendor_id:
        payload["meta_data"] = [{"key": "erp_vendor_id", "value": vendor_id}]
    if product.custom_metadata:
        meta_data = list(payload.get("meta_data") or [])
        for key, value in product.custom_metadata.items():
            meta_data.append({"key": str(key), "value": value})
        payload["meta_data"] = meta_data
    payload.update(
        product_taxonomy_payload(
            db,
            company_id=product.company_id,
            product=product,
            require_mappings=require_taxonomy_mappings,
        )
    )
    return payload


def enqueue_product_sync(
    db: Session,
    *,
    company_id: str | None,
    product: Product,
    ensure_taxonomies: bool = False,
) -> SyncOutbox:
    scoped_company_id = require_company_id(company_id)
    if ensure_taxonomies:
        sync_product_taxonomies(db, company_id=scoped_company_id, product=product)
    # Product saves happen in interactive API requests. Do not issue taxonomy
    # writes to WooCommerce here: the managed worker owns all remote publishing.
    payload = build_woocommerce_product_payload(
        db,
        product,
        require_taxonomy_mappings=False,
    )
    payload_hash = hashlib.sha256(
        jsonlib.dumps(payload, sort_keys=True, ensure_ascii=True, default=str).encode("utf-8")
    ).hexdigest()
    outbox = enqueue_sync_outbox(
        db,
        company_id=scoped_company_id,
        operation="push",
        resource_type="product",
        resource_id=product.id,
        payload=payload,
        idempotency_key=f"{CONNECTOR}:{scoped_company_id}:push:product:{product.id}:{payload_hash}",
    )
    if product_requires_media_sync(db, company_id=scoped_company_id, product=product):
        enqueue_product_media_sync(db, company_id=scoped_company_id, product=product)
    if product_requires_video_sync(db, company_id=scoped_company_id, product=product):
        enqueue_product_video_sync(db, company_id=scoped_company_id, product=product)
    return outbox


def product_requires_media_sync(db: Session, *, company_id: str, product: Product) -> bool:
    mapping = db.scalar(
        select(ExternalResourceMap).where(
            ExternalResourceMap.company_id == company_id,
            ExternalResourceMap.connector == CONNECTOR,
            ExternalResourceMap.internal_resource_type == "product",
            ExternalResourceMap.internal_resource_id == product.id,
        )
    )
    images = product_images_for_sync(
        db,
        company_id=company_id,
        product_id=product.id,
        include_pending_removals=True,
    )
    visible_images = [image for image in images if image.sync_status != "pending_remove"]
    if mapping is None:
        return bool(visible_images)
    return any(_product_image_requires_sync(image) for image in images)


def product_requires_video_sync(db: Session, *, company_id: str, product: Product) -> bool:
    """Queue an empty manifest for mapped products so removed videos are cleared remotely."""

    if product_videos(db, product.id):
        return True
    return (
        db.scalar(
            select(ExternalResourceMap.id).where(
                ExternalResourceMap.company_id == company_id,
                ExternalResourceMap.connector == CONNECTOR,
                ExternalResourceMap.internal_resource_type == "product",
                ExternalResourceMap.internal_resource_id == product.id,
            )
        )
        is not None
    )


def product_has_media_sync_work(db: Session, *, company_id: str, product: Product) -> bool:
    images = product_images_for_sync(
        db,
        company_id=company_id,
        product_id=product.id,
        include_pending_removals=True,
    )
    for image in images:
        if image.sync_status != "synced":
            return True
        if _product_image_requires_sync(image):
            return True
    return False


def enqueue_product_media_sync(
    db: Session,
    *,
    company_id: str | None,
    product: Product,
) -> SyncOutbox:
    scoped_company_id = require_company_id(company_id)
    image_state = [
        {
            "id": image.id,
            "external_id": image.external_id,
            "url": image.url,
            "name": image.name,
            "alt_text": image.alt_text,
            "sort_order": image.sort_order,
            "sync_status": image.sync_status,
            "updated_at": image.updated_at.isoformat() if image.updated_at else None,
        }
        for image in product_images_for_sync(
            db,
            company_id=scoped_company_id,
            product_id=product.id,
            include_pending_removals=True,
        )
    ]
    payload_hash = hashlib.sha256(
        jsonlib.dumps(image_state, sort_keys=True, ensure_ascii=True, default=str).encode("utf-8")
    ).hexdigest()
    return enqueue_sync_outbox(
        db,
        company_id=scoped_company_id,
        operation="push_media",
        resource_type="product",
        resource_id=product.id,
        payload={"images": image_state},
        idempotency_key=(
            f"{CONNECTOR}:{scoped_company_id}:push_media:product:{product.id}:{payload_hash}"
        ),
    )


def _safe_media_sync_error(value: str | None) -> str | None:
    """Return actionable outbox diagnostics without leaking connector secrets."""
    if not value:
        return None
    message = str(value).replace("\n", " ").strip()
    message = re.sub(
        r"(?i)(authorization|password|secret|token|consumer_secret)\s*([:=])\s*[^\s,;&]+",
        r"\1\2[redacted]",
        message,
    )
    message = re.sub(
        r"(?i)(https?://)[^\s/@:]+:[^\s/@]+@",
        r"\1[redacted]@",
        message,
    )
    message = re.sub(
        r"(?i)(consumer_secret|password|secret|token)=([^&\s]+)",
        r"\1=[redacted]",
        message,
    )
    return message[:2000] or None


def list_failed_product_media_syncs(
    db: Session, *, company_id: str | None
) -> list[dict[str, object]]:
    """List failed product-media outbox work for an administrator dashboard."""
    scoped_company_id = require_company_id(company_id)
    records = db.scalars(
        select(SyncOutbox)
        .where(
            SyncOutbox.company_id == scoped_company_id,
            SyncOutbox.connector == CONNECTOR,
            SyncOutbox.resource_type == "product",
            SyncOutbox.operation == "push_media",
            SyncOutbox.status == "failed",
        )
        .order_by(SyncOutbox.updated_at.desc(), SyncOutbox.created_at.desc())
    ).all()
    rows: list[dict[str, object]] = []
    for record in records:
        if not record.resource_id:
            continue
        product = db.scalar(
            select(Product).where(
                Product.company_id == scoped_company_id,
                Product.id == record.resource_id,
            )
        )
        if product is None:
            continue
        rows.append(
            {
                "id": record.id,
                "product_id": product.id,
                "product_name": product.name,
                "sku": product.sku,
                "status": record.status,
                "attempts": record.attempts,
                "next_attempt_at": record.next_attempt_at,
                "last_error": _safe_media_sync_error(record.last_error),
                "created_at": record.created_at,
                "updated_at": record.updated_at,
            }
        )
    return rows


def retry_failed_product_media_sync(
    db: Session,
    *,
    company_id: str | None,
    user_id: str,
    product_id: str,
) -> SyncOutbox:
    """Requeue one product's current media state without duplicating old work."""
    scoped_company_id = require_company_id(company_id)
    product = db.scalar(
        select(Product).where(
            Product.company_id == scoped_company_id,
            Product.id == product_id,
        )
    )
    if product is None:
        raise ServiceError(404, "Product not found.")

    # Queue the product first so an interrupted product creation is safely
    # recovered before the media operation attempts to attach image IDs.
    enqueue_product_sync(db, company_id=scoped_company_id, product=product)
    current = enqueue_product_media_sync(db, company_id=scoped_company_id, product=product)
    stale = db.scalars(
        select(SyncOutbox).where(
            SyncOutbox.company_id == scoped_company_id,
            SyncOutbox.connector == CONNECTOR,
            SyncOutbox.resource_type == "product",
            SyncOutbox.operation == "push_media",
            SyncOutbox.resource_id == product.id,
            SyncOutbox.status == "failed",
            SyncOutbox.id != current.id,
        )
    ).all()
    for record in stale:
        record.status = "synced"
        record.last_error = None
        record.next_attempt_at = None
    db.flush()
    record_audit(
        db,
        action="woocommerce.product_media_retry_queued",
        company_id=scoped_company_id,
        user_id=user_id,
        entity_type="product",
        entity_id=product.id,
        metadata={"media_outbox_id": current.id, "superseded_failures": len(stale)},
    )
    return current


def retry_all_failed_product_media_syncs(
    db: Session, *, company_id: str | None, user_id: str
) -> int:
    scoped_company_id = require_company_id(company_id)
    product_ids = {
        str(product_id)
        for product_id in db.scalars(
            select(SyncOutbox.resource_id).where(
                SyncOutbox.company_id == scoped_company_id,
                SyncOutbox.connector == CONNECTOR,
                SyncOutbox.resource_type == "product",
                SyncOutbox.operation == "push_media",
                SyncOutbox.status == "failed",
                SyncOutbox.resource_id.is_not(None),
            )
        ).all()
        if product_id
    }
    queued = 0
    for product_id in product_ids:
        try:
            retry_failed_product_media_sync(
                db,
                company_id=scoped_company_id,
                user_id=user_id,
                product_id=product_id,
            )
        except ServiceError as exc:
            if exc.status_code != 404:
                raise
        else:
            queued += 1
    return queued


def enqueue_product_video_sync(
    db: Session,
    *,
    company_id: str | None,
    product: Product,
) -> SyncOutbox:
    scoped_company_id = require_company_id(company_id)
    video_state = [
        {
            "id": video.id,
            "source_type": video.source_type,
            "url": video.url,
            "name": video.name,
            "sort_order": video.sort_order,
            "external_id": video.external_id,
            "remote_url": video.remote_url,
            "sync_status": video.sync_status,
            "updated_at": video.updated_at.isoformat() if video.updated_at else None,
        }
        for video in product_videos(db, product.id)
    ]
    payload_hash = hashlib.sha256(
        jsonlib.dumps(video_state, sort_keys=True, ensure_ascii=True, default=str).encode("utf-8")
    ).hexdigest()
    return enqueue_sync_outbox(
        db,
        company_id=scoped_company_id,
        operation="push_videos",
        resource_type="product",
        resource_id=product.id,
        payload={"videos": video_state},
        idempotency_key=(
            f"{CONNECTOR}:{scoped_company_id}:push_videos:product:{product.id}:{payload_hash}"
        ),
    )


def enqueue_products_for_sync(
    db: Session, company_id: str, *, vendor_id: str | None = None
) -> int:
    scoped_company_id = require_company_id(company_id)
    mapped_product_ids = {
        str(internal_id)
        for internal_id in db.scalars(
            select(ExternalResourceMap.internal_resource_id).where(
                ExternalResourceMap.company_id == scoped_company_id,
                ExternalResourceMap.connector == CONNECTOR,
                ExternalResourceMap.internal_resource_type == "product",
            )
        ).all()
    }
    products = db.scalars(
        select(Product)
        .where(
            Product.company_id == scoped_company_id,
        )
        .order_by(Product.created_at)
    ).all()
    published_product_ids = {
        str(product_id)
        for product_id in db.scalars(
            select(ProductChannelListing.product_id).where(
                ProductChannelListing.company_id == scoped_company_id,
                ProductChannelListing.channel == CONNECTOR,
                ProductChannelListing.listing_status == "published",
            )
        ).all()
    }
    queued = 0
    for product in products:
        # Company-owned catalog behavior remains unchanged. Vendor-owned products
        # enter the shared storefront only when their channel listing is public.
        if product.vendor_id and product.id not in published_product_ids:
            continue
        if vendor_id and not product_belongs_to_vendor(
            db,
            company_id=scoped_company_id,
            product=product,
            vendor_id=vendor_id,
        ):
            continue
        if product.status == "archived" and product.id not in mapped_product_ids:
            continue
        enqueue_product_sync(
            db,
            company_id=scoped_company_id,
            product=product,
            ensure_taxonomies=False,
        )
        queued += 1
    return queued


def pending_product_media_ids_query(company_id: str):
    return (
        # PostgreSQL cannot apply DISTINCT to Product's JSON columns. Select
        # only the scalar primary key here, then load the matching products.
        select(Product.id)
        .join(ProductImage, ProductImage.product_id == Product.id)
        .where(
            Product.company_id == company_id,
            ProductImage.company_id == company_id,
            (
                (ProductImage.sync_status != "synced")
                | (
                    ProductImage.external_id.is_(None)
                    & (ProductImage.sync_status != "pending_remove")
                )
            ),
        )
        .distinct()
    )


def enqueue_pending_product_media_for_sync(
    db: Session, company_id: str, *, vendor_id: str | None = None
) -> int:
    scoped_company_id = require_company_id(company_id)
    stale_media_records = db.scalars(
        select(SyncOutbox).where(
            SyncOutbox.company_id == scoped_company_id,
            SyncOutbox.connector == CONNECTOR,
            SyncOutbox.operation == "push_media",
            SyncOutbox.resource_type == "product",
            SyncOutbox.status.in_({"pending", "failed"}),
        )
    ).all()
    for record in stale_media_records:
        product = db.scalar(
            select(Product).where(
                Product.company_id == scoped_company_id,
                Product.id == record.resource_id,
            )
        )
        if product is None:
            continue
        if vendor_id and not product_belongs_to_vendor(
            db,
            company_id=scoped_company_id,
            product=product,
            vendor_id=vendor_id,
        ):
            continue
        if not product_has_media_sync_work(
            db,
            company_id=scoped_company_id,
            product=product,
        ):
            record.status = "synced"
            record.last_error = None
            record.next_attempt_at = None
    product_ids = db.scalars(pending_product_media_ids_query(scoped_company_id)).all()
    products = db.scalars(
        select(Product)
        .where(Product.id.in_(product_ids))
        .order_by(Product.created_at, Product.id)
    ).all()
    published_product_ids = {
        str(product_id)
        for product_id in db.scalars(
            select(ProductChannelListing.product_id).where(
                ProductChannelListing.company_id == scoped_company_id,
                ProductChannelListing.channel == CONNECTOR,
                ProductChannelListing.listing_status == "published",
            )
        ).all()
    }
    queued = 0
    for product in products:
        # Company-owned catalog behavior remains unchanged. Vendor-owned products
        # enter the shared storefront only when their channel listing is public.
        if product.vendor_id and product.id not in published_product_ids:
            continue
        if vendor_id and not product_belongs_to_vendor(
            db,
            company_id=scoped_company_id,
            product=product,
            vendor_id=vendor_id,
        ):
            continue
        enqueue_product_media_sync(db, company_id=scoped_company_id, product=product)
        queued += 1
    return queued


def woocommerce_sync_outbox_status(
    db: Session, company_id: str, *, vendor_id: str | None = None
) -> dict[str, object]:
    scoped_company_id = require_company_id(company_id)
    records = db.scalars(
        select(SyncOutbox).where(
            SyncOutbox.company_id == scoped_company_id,
            SyncOutbox.connector == CONNECTOR,
            SyncOutbox.status.in_({"pending", "failed", "processing"}),
        )
    ).all()
    if vendor_id:
        records = [
            record
            for record in records
            if _sync_outbox_record_belongs_to_vendor(
                db,
                company_id=scoped_company_id,
                record=record,
                vendor_id=vendor_id,
            )
        ]
    pending_product_pushes = 0
    pending_media_pushes = 0
    pending_video_pushes = 0
    failed_product_pushes = 0
    failed_media_pushes = 0
    failed_video_pushes = 0
    last_media_error: str | None = None
    last_media_error_at = None
    last_video_error: str | None = None
    last_video_error_at = None
    for record in records:
        is_failed = record.status == "failed"
        if record.resource_type == "product" and record.operation == "push":
            if is_failed:
                failed_product_pushes += 1
            else:
                pending_product_pushes += 1
        elif record.resource_type == "product" and record.operation == "push_media":
            if is_failed:
                failed_media_pushes += 1
                if record.last_error:
                    updated_at = record.updated_at or record.created_at
                    if last_media_error_at is None or updated_at > last_media_error_at:
                        last_media_error_at = updated_at
                        last_media_error = record.last_error
            else:
                pending_media_pushes += 1
        elif record.resource_type == "product" and record.operation == "push_videos":
            if is_failed:
                failed_video_pushes += 1
                if record.last_error:
                    updated_at = record.updated_at or record.created_at
                    if last_video_error_at is None or updated_at > last_video_error_at:
                        last_video_error_at = updated_at
                        last_video_error = record.last_error
            else:
                pending_video_pushes += 1
    return {
        "pending_product_pushes": pending_product_pushes,
        "pending_media_pushes": pending_media_pushes,
        "pending_video_pushes": pending_video_pushes,
        "failed_product_pushes": failed_product_pushes,
        "failed_media_pushes": failed_media_pushes,
        "failed_video_pushes": failed_video_pushes,
        "last_media_error": last_media_error,
        "last_video_error": last_video_error,
    }


def woocommerce_sync_job_status(db: Session, company_id: str) -> dict[str, object]:
    scoped_company_id = require_company_id(company_id)
    jobs = db.scalars(
        select(SyncRunLog)
        .where(
            SyncRunLog.company_id == scoped_company_id,
            SyncRunLog.connector == CONNECTOR,
            SyncRunLog.status.in_(SYNC_RUN_ACTIVE_STATUSES),
        )
        .order_by(SyncRunLog.started_at.desc(), SyncRunLog.id.desc())
    ).all()
    latest = jobs[0] if jobs else None
    return {
        "queued_sync_runs": sum(1 for job in jobs if job.status == "queued"),
        "running_sync_runs": sum(1 for job in jobs if job.status == "running"),
        "active_sync_run_id": latest.id if latest is not None else None,
        "active_sync_worker_id": latest.worker_id if latest is not None else None,
    }


def default_woocommerce_sync_stats() -> dict[str, object]:
    return {
        "sync_mode": "incremental",
        "current_phase": None,
        "pulled_categories": 0,
        "pulled_brands": 0,
        "pulled_products": 0,
        "pulled_customers": 0,
        "pulled_orders": 0,
        "reconciled_product_ids": 0,
        "archived_products": 0,
        "pushed_records": 0,
        "pushed_media_records": 0,
        "pushed_video_records": 0,
        "queued_product_pushes": 0,
        "queued_media_pushes": 0,
        "queued_video_pushes": 0,
        "failed_records": 0,
        "deferred_media_records": 0,
        "deferred_video_records": 0,
        "pending_product_pushes": 0,
        "pending_media_pushes": 0,
        "pending_video_pushes": 0,
        "failed_product_pushes": 0,
        "failed_media_pushes": 0,
        "failed_video_pushes": 0,
        "synced_categories": 0,
        "synced_brands": 0,
        "failed_taxonomies": 0,
        "taxonomy_errors": [],
    }


def _woocommerce_sync_active_key(company_id: str, vendor_id: str | None = None) -> str:
    # Every user in a company publishes to the same configured WooCommerce
    # store. A company-wide key prevents separate vendor jobs from bursting
    # requests at that store.
    del vendor_id
    return f"{CONNECTOR}:{company_id}"


def enqueue_woocommerce_sync_run(
    db: Session,
    *,
    company_id: str | None,
    sync_mode: str = "incremental",
    vendor_id: str | None = None,
) -> tuple[SyncRunLog, bool]:
    """Create one durable WooCommerce sync job, or return the active job.

    ``active_key`` is unique while a run is queued/running.  The pre-query is
    friendly to the desktop (duplicate clicks reuse the same job); the unique
    constraint still protects concurrent API requests in PostgreSQL.
    """

    scoped_company_id = require_company_id(company_id)
    normalized_mode = normalize_woocommerce_sync_mode(sync_mode)
    active_key = _woocommerce_sync_active_key(scoped_company_id)
    existing = db.scalar(
        select(SyncRunLog)
        .where(
            SyncRunLog.company_id == scoped_company_id,
            SyncRunLog.connector == CONNECTOR,
            SyncRunLog.active_key == active_key,
            SyncRunLog.status.in_(SYNC_RUN_ACTIVE_STATUSES),
        )
        .order_by(SyncRunLog.started_at.desc(), SyncRunLog.id.desc())
    )
    if existing is not None:
        if not existing.active_key:
            existing.active_key = active_key
            db.flush()
        return existing, False

    stats = default_woocommerce_sync_stats()
    stats["sync_mode"] = normalized_mode
    stats["scope"] = "vendor" if vendor_id else "company"
    stats["vendor_id"] = vendor_id
    run_log = SyncRunLog(
        company_id=scoped_company_id,
        connector=CONNECTOR,
        direction=(
            "outbound"
            if normalized_mode == "products" and vendor_id
            else "both"
            if normalized_mode in {"incremental", "products"}
            else "inbound"
        ),
        active_key=active_key,
        status="queued",
        stats=stats,
    )
    db.add(run_log)
    try:
        db.flush()
    except IntegrityError:
        # The request did not make any other changes.  Recover the competing
        # durable job instead of returning an opaque 500 to a second Sync click.
        db.rollback()
        existing = db.scalar(select(SyncRunLog).where(SyncRunLog.active_key == active_key))
        if existing is not None:
            return existing, False
        raise
    return run_log, True


def enqueue_pending_woocommerce_sync_runs(db: Session) -> int:
    """Schedule one shared outbound run for each company with eligible work."""

    now = utcnow()
    company_ids = db.scalars(
        select(SyncOutbox.company_id)
        .where(
            SyncOutbox.connector == CONNECTOR,
            SyncOutbox.company_id.is_not(None),
            SyncOutbox.status.in_({"pending", "failed"}),
            SyncOutbox.attempts < SYNC_OUTBOX_MAX_ATTEMPTS,
            (SyncOutbox.next_attempt_at.is_(None)) | (SyncOutbox.next_attempt_at <= now),
        )
        .distinct()
    ).all()
    created = 0
    for company_id in company_ids:
        _run, was_created = enqueue_woocommerce_sync_run(
            db,
            company_id=company_id,
            sync_mode="outbox",
        )
        created += int(was_created)
    return created


def recover_stale_woocommerce_sync_records(
    db: Session,
    *,
    now=None,
) -> dict[str, int]:
    """Requeue abandoned worker leases and stale outbox processing records."""

    current_time = now or utcnow()
    recovered_runs = 0
    recovered_outbox = 0
    stale_runs = db.scalars(
        select(SyncRunLog).where(
            SyncRunLog.connector == CONNECTOR,
            SyncRunLog.status == "running",
            (SyncRunLog.lease_expires_at.is_(None)) | (SyncRunLog.lease_expires_at <= current_time),
        )
    ).all()
    for run_log in stale_runs:
        if not run_log.company_id:
            run_log.status = "failed"
            run_log.finished_at = current_time
            run_log.active_key = None
            run_log.error = "Sync job recovery failed because its company scope is missing."
            continue
        run_log.status = "queued"
        run_log.active_key = _woocommerce_sync_active_key(
            run_log.company_id,
            str((run_log.stats or {}).get("vendor_id") or "") or None,
        )
        run_log.lease_expires_at = None
        run_log.worker_id = None
        run_log.error = "Recovered after the previous worker lease expired."
        stats = dict(run_log.stats or {})
        stats["recovered_runs"] = int(stats.get("recovered_runs", 0)) + 1
        run_log.stats = dict(stats)
        recovered_runs += 1

    stale_outbox_cutoff = current_time - timedelta(seconds=SYNC_OUTBOX_STALE_SECONDS)
    stale_outbox = db.scalars(
        select(SyncOutbox).where(
            SyncOutbox.connector == CONNECTOR,
            SyncOutbox.status == "processing",
            (SyncOutbox.updated_at.is_(None)) | (SyncOutbox.updated_at <= stale_outbox_cutoff),
        )
    ).all()
    for record in stale_outbox:
        record.status = "pending"
        record.next_attempt_at = current_time
        record.last_error = "Recovered after a worker stopped while processing this record."
        recovered_outbox += 1

    if recovered_runs or recovered_outbox:
        db.flush()
    return {"recovered_runs": recovered_runs, "recovered_outbox": recovered_outbox}


def claim_next_woocommerce_sync_run(
    db: Session,
    *,
    worker_id: str,
) -> SyncRunLog | None:
    """Lease the oldest queued job.  PostgreSQL claims it row-by-row safely."""

    query = (
        select(SyncRunLog)
        .where(
            SyncRunLog.connector == CONNECTOR,
            SyncRunLog.status == "queued",
            (SyncRunLog.next_attempt_at.is_(None)) | (SyncRunLog.next_attempt_at <= utcnow()),
        )
        .order_by(SyncRunLog.started_at.asc(), SyncRunLog.id.asc())
        .limit(1)
    )
    if db.get_bind().dialect.name != "sqlite":
        query = query.with_for_update(skip_locked=True)
    run_log = db.scalar(query)
    if run_log is None:
        return None
    if not run_log.company_id:
        run_log.status = "failed"
        run_log.finished_at = utcnow()
        run_log.active_key = None
        run_log.error = "Queued sync job has no company scope."
        db.flush()
        return None
    run_log.status = "running"
    run_log.worker_id = worker_id
    run_log.attempts += 1
    run_log.lease_expires_at = utcnow() + timedelta(seconds=SYNC_JOB_LEASE_SECONDS)
    run_log.next_attempt_at = None
    run_log.error = None
    db.flush()
    return run_log


def touch_woocommerce_sync_lease(db: Session, run_log: SyncRunLog) -> None:
    if run_log.status != "running":
        return
    run_log.lease_expires_at = utcnow() + timedelta(seconds=SYNC_JOB_LEASE_SECONDS)


def make_woocommerce_request(
    db: Session,
    company_id: str,
    method: str,
    resource_path: str,
    json_data: dict | None = None,
    params: dict[str, object] | None = None,
    timeout: float = 10.0,
) -> WooCommerceRequestResult:
    config = load_woocommerce_config(db, company_id)
    if config is None:
        raise ServiceError(404, "WooCommerce is not configured.")

    candidates = woocommerce_rest_mode_candidates(config.rest_api_mode)
    last_result: WooCommerceRequestResult | None = None
    last_auth_result: WooCommerceRequestResult | None = None
    last_request_error: ServiceError | None = None
    for index, rest_api_mode in enumerate(candidates):
        for auth_mode in ("basic", "query"):
            try:
                result = _woocommerce_request_once(
                    db,
                    company_id,
                    method,
                    resource_path,
                    rest_api_mode=rest_api_mode,
                    auth_mode=auth_mode,
                    json_data=json_data,
                    params=params,
                    timeout=timeout,
                )
            except ServiceError as exc:
                if exc.status_code == 503:
                    last_request_error = exc
                    continue
                raise
            last_result = result
            status_code = result.response.status_code
            if 200 <= status_code < 300:
                if result.rest_api_mode != config.rest_api_mode:
                    store_woocommerce_rest_api_mode(
                        db,
                        company_id=company_id,
                        rest_api_mode=result.rest_api_mode,
                    )
                return result
            if status_code == 429:
                raise WooCommerceRateLimitError(
                    result,
                    _rate_limit_delay_seconds(result.response),
                )
            if status_code in {401, 403}:
                last_auth_result = result
                continue
            if status_code != 404:
                return result
            break
        if index == len(candidates) - 1 and (
            last_auth_result is not None or last_result is not None
        ):
            return last_auth_result or last_result

    if last_result is not None:
        return last_auth_result or last_result
    if last_request_error is not None:
        raise last_request_error
    raise ServiceError(503, "WooCommerce request failed unexpectedly.")


def _coerce_woo_image_identifier(value: object) -> int | str | None:
    if value is None:
        return None
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return str(value)


def _remote_product_images(item: dict[str, object]) -> list[dict[str, object]]:
    images = item.get("images")
    if not isinstance(images, list):
        return []
    return [image for image in images if isinstance(image, dict)]


def fetch_remote_product_payload(
    db: Session,
    *,
    company_id: str,
    external_product_id: str,
) -> dict[str, object]:
    response = make_woocommerce_request(
        db,
        company_id,
        "GET",
        f"/products/{external_product_id}",
    )
    if response.response.status_code not in {200, 201}:
        raise ServiceError(
            502,
            format_remote_http_error(action="Fetch product media", result=response),
        )
    payload = response.response.json()
    if not isinstance(payload, dict):
        raise ServiceError(502, "WooCommerce product fetch returned an invalid payload.")
    return payload


def reconcile_product_images_from_remote(
    db: Session,
    *,
    company_id: str,
    product: Product,
    remote_images: list[dict[str, object]],
) -> None:
    seen_external_ids: set[str] = set()
    now = utcnow()
    existing_images = product_images_for_sync(
        db,
        company_id=company_id,
        product_id=product.id,
        include_pending_removals=True,
    )
    by_external_id = {image.external_id: image for image in existing_images if image.external_id}
    unsynced_by_url = {
        image.url: image
        for image in existing_images
        if not image.external_id and image.sync_status != "pending_remove"
    }

    for index, image_data in enumerate(remote_images):
        source_url = image_data.get("src")
        if not isinstance(source_url, str) or not source_url:
            continue
        image_external_id = str(image_data.get("id")) if image_data.get("id") is not None else None
        image = by_external_id.get(image_external_id) if image_external_id else None
        if image is None:
            image = unsynced_by_url.get(source_url)
        if image is None:
            image = ProductImage(
                company_id=company_id,
                product_id=product.id,
                url=source_url,
            )
            db.add(image)
        image.external_id = image_external_id
        if image.sync_status == "pending_update":
            image.last_synced_at = now
            if image_external_id:
                seen_external_ids.add(image_external_id)
            continue
        if image.sync_status == "pending_remove":
            image.last_synced_at = now
            if image_external_id:
                seen_external_ids.add(image_external_id)
            continue
        image.url = source_url
        image.name = image_data.get("name") if isinstance(image_data.get("name"), str) else None
        image.alt_text = image_data.get("alt") if isinstance(image_data.get("alt"), str) else None
        image.sort_order = index
        image.sync_status = "synced"
        image.last_synced_at = now
        if image_external_id:
            seen_external_ids.add(image_external_id)

    for image in existing_images:
        if not image.external_id:
            continue
        if image.external_id in seen_external_ids:
            continue
        if image.sync_status == "pending_remove":
            db.delete(image)
            continue
        if image.sync_status in {"pending_add", "pending_update"}:
            continue
        db.delete(image)

    db.flush()


def build_woocommerce_product_media_payload(
    db: Session,
    *,
    company_id: str,
    product: Product,
    external_product_id: str,
    checkpoint: Callable[[], None] | None = None,
) -> list[dict[str, object]]:
    remote_payload = fetch_remote_product_payload(
        db,
        company_id=company_id,
        external_product_id=external_product_id,
    )
    remote_images = _remote_product_images(remote_payload)
    local_images = product_images_for_sync(
        db,
        company_id=company_id,
        product_id=product.id,
        include_pending_removals=True,
    )
    local_by_external_id = {image.external_id: image for image in local_images if image.external_id}
    local_pending_by_url = {
        image.url: image
        for image in local_images
        if not image.external_id and image.sync_status != "pending_remove"
    }

    merged: list[dict[str, object]] = []
    seen_external_ids: set[str] = set()
    seen_local_ids: set[str] = set()
    for remote_image in remote_images:
        remote_id = remote_image.get("id")
        remote_external_id = str(remote_id) if remote_id is not None else None
        local_image = local_by_external_id.get(remote_external_id) if remote_external_id else None
        if local_image is None:
            remote_src = remote_image.get("src")
            if isinstance(remote_src, str):
                local_image = local_pending_by_url.get(remote_src)
        if local_image is not None and local_image.sync_status == "pending_remove":
            if remote_external_id:
                seen_external_ids.add(remote_external_id)
            continue
        if local_image is not None:
            payload = _woocommerce_image_payload(local_image, product.name) or {}
            if remote_id is not None:
                payload.pop("src", None)
                payload["id"] = _coerce_woo_image_identifier(remote_id)
            if payload:
                merged.append(payload)
            if remote_external_id:
                seen_external_ids.add(remote_external_id)
            seen_local_ids.add(local_image.id)
            continue
        if remote_id is not None:
            merged.append({"id": _coerce_woo_image_identifier(remote_id)})
            if remote_external_id:
                seen_external_ids.add(remote_external_id)
            continue
        if isinstance(remote_image.get("src"), str):
            merged.append({"src": remote_image["src"]})

    for image in local_images:
        if image.sync_status == "pending_remove":
            continue
        if image.id in seen_local_ids:
            continue
        if not image.external_id:
            upload_product_image_to_wordpress(
                db,
                company_id=company_id,
                image=image,
                checkpoint=checkpoint,
            )
        if image.external_id and image.external_id in seen_external_ids:
            continue
        payload = _woocommerce_image_payload(image, product.name)
        if payload is not None:
            merged.append(payload)
        if image.external_id:
            seen_external_ids.add(image.external_id)

    return merged


def create_sync_conflict(
    db: Session,
    company_id: str,
    resource_type: str,
    resource_id: str | None,
    external_resource_id: str | None,
    conflict_type: str,
    local_payload: dict,
    remote_payload: dict,
) -> SyncConflict:
    conflict = SyncConflict(
        company_id=company_id,
        connector=CONNECTOR,
        resource_type=resource_type,
        resource_id=resource_id,
        external_resource_id=external_resource_id,
        conflict_type=conflict_type,
        local_payload=local_payload,
        remote_payload=remote_payload,
        status="open",
    )
    db.add(conflict)
    db.flush()
    return conflict


def map_woocommerce_order_status(status: str | None) -> str:
    if status == "pending":
        return "pending"
    if status in {"processing", "on-hold"}:
        return "confirmed"
    if status == "completed":
        return "delivered"
    if status == "cancelled":
        return "cancelled"
    if status == "refunded":
        return "refunded"
    return "pending"


def apply_woocommerce_order_status(
    db: Session,
    *,
    company_id: str,
    order: Order,
    woo_status: str | None,
) -> None:
    target_status = map_woocommerce_order_status(woo_status)
    if order.status == target_status:
        return

    from erp.packages.core.order_services import change_order_status
    from erp.packages.core.schemas import OrderStatusChange

    if target_status in ORDER_PROGRESS_STATUSES:
        try:
            current_index = ORDER_PROGRESS_STATUSES.index(order.status)
            target_index = ORDER_PROGRESS_STATUSES.index(target_status)
        except ValueError:
            current_index = target_index = -1
        if current_index >= 0 and target_index > current_index:
            transition_path = ORDER_PROGRESS_STATUSES[current_index + 1 : target_index + 1]
        else:
            transition_path = [target_status]
    elif target_status == "refunded" and order.status != "delivered":
        try:
            current_index = ORDER_PROGRESS_STATUSES.index(order.status)
        except ValueError:
            transition_path = [target_status]
        else:
            transition_path = ORDER_PROGRESS_STATUSES[current_index + 1 :] + ["refunded"]
    else:
        transition_path = [target_status]

    for status in transition_path:
        if order.status == status:
            continue
        change_order_status(
            db,
            company_id=company_id,
            user_id=woocommerce_sync_user_id(db, company_id),
            order_id=order.id,
            payload=OrderStatusChange(status=status, reason="WooCommerce sync update"),
        )


def _online_order_stock_issue(
    db: Session,
    *,
    company_id: str,
    order: Order,
    details: list[dict[str, object]],
) -> None:
    metadata = dict(order.metadata_json or {})
    metadata["online_stock_issue"] = {
        "message": "Online order needs a stock reconciliation before it can be deducted.",
        "items": details,
        "updated_at": utcnow().isoformat(),
    }
    order.metadata_json = metadata
    order.reservation_status = "stock_issue"
    record_audit(
        db,
        action="commerce.online_stock_reconciliation_required",
        company_id=company_id,
        entity_type="order",
        entity_id=order.id,
        metadata={"order_number": order.order_number, "items": details},
    )


def deduct_woocommerce_order_stock(
    db: Session,
    *,
    company_id: str,
    order: Order,
) -> bool:
    """Deduct each vendor's published online sale from that vendor's shop stock once."""
    if order.sales_channel != "woocommerce" or order.status in {"cancelled", "refunded"}:
        return False
    if order.reservation_status in {"deducted", "baseline"}:
        return True

    from erp.packages.core.inventory_services import current_stock, record_stock_movement
    from erp.packages.core.shop_services import (
        queue_published_shop_stock_sync,
        sync_product_catalog_quantity_from_shop,
        vendor_shop_warehouse,
    )

    rows = list(
        db.scalars(
            select(VendorOrderItem).where(
                VendorOrderItem.company_id == company_id,
                VendorOrderItem.order_id == order.id,
            )
        ).all()
    )
    required: dict[tuple[str, str, str | None], int] = {}
    for row in rows:
        key = (row.vendor_id, row.product_id, row.variant_id)
        required[key] = required.get(key, 0) + row.quantity
    if not required:
        # Company-owned order lines continue through the normal company inventory
        # flow. This helper only enforces the dedicated vendor shop balance.
        return False

    shortages: list[dict[str, object]] = []
    warehouses: dict[str, Warehouse] = {}
    for (vendor_id, product_id, variant_id), quantity in required.items():
        warehouse = warehouses.setdefault(
            vendor_id, vendor_shop_warehouse(db, company_id, vendor_id)
        )
        available = current_stock(
            db,
            company_id=company_id,
            warehouse_id=warehouse.id,
            product_id=product_id,
            variant_id=variant_id,
        )
        if available < quantity:
            shortages.append(
                {
                    "vendor_id": vendor_id,
                    "product_id": product_id,
                    "variant_id": variant_id,
                    "ordered_quantity": quantity,
                    "available_quantity": available,
                }
            )
    if shortages:
        _online_order_stock_issue(
            db, company_id=company_id, order=order, details=shortages
        )
        return False

    sync_user_id = woocommerce_sync_user_id(db, company_id)
    for (vendor_id, product_id, variant_id), quantity in required.items():
        record_stock_movement(
            db,
            company_id=company_id,
            user_id=sync_user_id,
            payload=StockMovementCreate(
                movement_type="stock_out",
                warehouse_id=warehouses[vendor_id].id,
                product_id=product_id,
                variant_id=variant_id,
                quantity=quantity,
                reference_type="woocommerce_order",
                reference_id=order.id,
                reason="WooCommerce order stock deduction.",
                metadata={"external_order_id": order.external_order_id or ""},
            ),
        )
        if variant_id is None:
            sync_product_catalog_quantity_from_shop(
                db,
                company_id=company_id,
                vendor_id=vendor_id,
                product_id=product_id,
            )
            queue_published_shop_stock_sync(
                db,
                company_id=company_id,
                vendor_id=vendor_id,
                product_id=product_id,
            )
    metadata = dict(order.metadata_json or {})
    metadata.pop("online_stock_issue", None)
    order.metadata_json = metadata
    order.reservation_status = "deducted"
    record_audit(
        db,
        action="commerce.woocommerce_order_stock_deducted",
        company_id=company_id,
        user_id=sync_user_id,
        entity_type="order",
        entity_id=order.id,
        metadata={"order_number": order.order_number, "line_count": len(required)},
    )
    return True


def restore_cancelled_woocommerce_order_stock(
    db: Session,
    *,
    company_id: str,
    order: Order,
) -> bool:
    """Restore a cancelled online order exactly once; refunds need physical receipt."""
    if order.sales_channel != "woocommerce" or order.reservation_status != "deducted":
        return False
    from erp.packages.core.inventory_services import record_stock_movement
    from erp.packages.core.shop_services import (
        queue_published_shop_stock_sync,
        sync_product_catalog_quantity_from_shop,
        vendor_shop_warehouse,
    )

    rows = list(
        db.scalars(
            select(VendorOrderItem).where(
                VendorOrderItem.company_id == company_id,
                VendorOrderItem.order_id == order.id,
            )
        ).all()
    )
    restored: dict[tuple[str, str, str | None], int] = {}
    for row in rows:
        key = (row.vendor_id, row.product_id, row.variant_id)
        restored[key] = restored.get(key, 0) + row.quantity
    sync_user_id = woocommerce_sync_user_id(db, company_id)
    for (vendor_id, product_id, variant_id), quantity in restored.items():
        warehouse = vendor_shop_warehouse(db, company_id, vendor_id)
        record_stock_movement(
            db,
            company_id=company_id,
            user_id=sync_user_id,
            payload=StockMovementCreate(
                movement_type="stock_in",
                warehouse_id=warehouse.id,
                product_id=product_id,
                variant_id=variant_id,
                quantity=quantity,
                reference_type="woocommerce_order_cancelled",
                reference_id=order.id,
                reason="Cancelled WooCommerce order stock restored.",
                metadata={"external_order_id": order.external_order_id or ""},
            ),
        )
        if variant_id is None:
            sync_product_catalog_quantity_from_shop(
                db,
                company_id=company_id,
                vendor_id=vendor_id,
                product_id=product_id,
            )
            queue_published_shop_stock_sync(
                db,
                company_id=company_id,
                vendor_id=vendor_id,
                product_id=product_id,
            )
    order.reservation_status = "restored"
    record_audit(
        db,
        action="commerce.woocommerce_order_stock_restored",
        company_id=company_id,
        user_id=sync_user_id,
        entity_type="order",
        entity_id=order.id,
        metadata={"order_number": order.order_number, "line_count": len(restored)},
    )
    return bool(restored)


def extract_vendor_id_from_item(item: dict) -> str | None:
    top_level = item.get("vendor_id") or item.get("erp_vendor_id")
    if top_level:
        return str(top_level)
    meta_data = item.get("meta_data")
    if isinstance(meta_data, list):
        for entry in meta_data:
            if not isinstance(entry, dict):
                continue
            key = str(entry.get("key") or "")
            if key in {"vendor_id", "erp_vendor_id"}:
                value = entry.get("value")
                if value not in {None, ""}:
                    return str(value)
    return None


def product_belongs_to_vendor(
    db: Session,
    *,
    company_id: str,
    product: Product | None = None,
    product_id: str | None = None,
    item: dict | None = None,
    vendor_id: str,
) -> bool:
    """Resolve vendor ownership without trusting a client-supplied scope."""

    if item is not None and extract_vendor_id_from_item(item) == vendor_id:
        return True
    if product is None and product_id:
        product = db.scalar(
            select(Product).where(Product.company_id == company_id, Product.id == product_id)
        )
    if product is None and item is not None:
        external_id = item.get("id")
        if external_id is not None:
            mapping = get_external_resource_map(
                db,
                company_id=company_id,
                resource_type="product",
                external_id=str(external_id),
            )
            if mapping is not None:
                product = db.scalar(
                    select(Product).where(
                        Product.company_id == company_id,
                        Product.id == mapping.internal_resource_id,
                    )
                )
    if product is None:
        return False
    if product.vendor_id == vendor_id:
        return True
    return (
        db.scalar(
            select(VendorProduct.id).where(
                VendorProduct.company_id == company_id,
                VendorProduct.product_id == product.id,
                VendorProduct.vendor_id == vendor_id,
            )
        )
        is not None
    )


def sync_single_category(db: Session, company_id: str, item: dict) -> Category:
    external_id = str(item["id"])
    mapping = get_external_resource_map(
        db, company_id=company_id, resource_type="category", external_id=external_id
    )
    category = None
    if mapping is not None:
        category = db.scalar(
            select(Category).where(
                Category.company_id == company_id, Category.id == mapping.internal_resource_id
            )
        )
    slug = str(item.get("slug") or "").strip()
    name = str(item.get("name") or slug or f"WooCommerce category {external_id}").strip()
    if category is None and slug:
        category = db.scalar(
            select(Category).where(Category.company_id == company_id, Category.slug == slug)
        )
    if category is None:
        category = Category(
            company_id=company_id, name=name, slug=slug or f"woo-category-{external_id}"
        )
        db.add(category)
        db.flush()
    else:
        category.name = name
        category.slug = slug or category.slug
    category.description = item.get("description") or category.description
    category.is_active = True
    upsert_external_resource_map(
        db,
        company_id=company_id,
        resource_type="category",
        internal_id=category.id,
        external_id=external_id,
    )
    return category


def sync_single_brand(db: Session, company_id: str, item: dict) -> Brand:
    external_id = str(item["id"])
    mapping = get_external_resource_map(
        db, company_id=company_id, resource_type="brand", external_id=external_id
    )
    brand = None
    if mapping is not None:
        brand = db.scalar(
            select(Brand).where(
                Brand.company_id == company_id, Brand.id == mapping.internal_resource_id
            )
        )
    slug = str(item.get("slug") or "").strip()
    name = str(item.get("name") or slug or f"WooCommerce brand {external_id}").strip()
    if brand is None and slug:
        brand = db.scalar(select(Brand).where(Brand.company_id == company_id, Brand.slug == slug))
    if brand is None:
        brand = Brand(company_id=company_id, name=name, slug=slug or f"woo-brand-{external_id}")
        db.add(brand)
        db.flush()
    else:
        brand.name = name
        brand.slug = slug or brand.slug
    brand.description = item.get("description") or brand.description
    brand.is_active = True
    upsert_external_resource_map(
        db,
        company_id=company_id,
        resource_type="brand",
        internal_id=brand.id,
        external_id=external_id,
    )
    return brand


def apply_product_taxonomies_from_woocommerce(
    db: Session, *, company_id: str, product: Product, item: dict
) -> None:
    remote_categories = item.get("categories")
    if isinstance(remote_categories, list):
        category_ids: list[str] = []
        for remote in remote_categories:
            if not isinstance(remote, dict) or remote.get("id") is None:
                continue
            mapping = get_external_resource_map(
                db, company_id=company_id, resource_type="category", external_id=str(remote["id"])
            )
            category = None
            if mapping is not None:
                category = db.scalar(
                    select(Category).where(Category.id == mapping.internal_resource_id)
                )
            if category is None:
                category = sync_single_category(db, company_id, remote)
            category_ids.append(category.id)
        if category_ids:
            product.category_id = category_ids[0]
            db.query(ProductCategoryLink).filter(
                ProductCategoryLink.product_id == product.id
            ).delete()
            for position, category_id in enumerate(category_ids):
                db.add(
                    ProductCategoryLink(
                        company_id=company_id,
                        product_id=product.id,
                        category_id=category_id,
                        is_primary=position == 0,
                        sort_order=position,
                    )
                )
    remote_brands = item.get("brands")
    if not isinstance(remote_brands, list):
        remote_brands = [item["brand"]] if isinstance(item.get("brand"), dict) else []
    for remote in remote_brands:
        if not isinstance(remote, dict) or remote.get("id") is None:
            continue
        mapping = get_external_resource_map(
            db, company_id=company_id, resource_type="brand", external_id=str(remote["id"])
        )
        brand = None
        if mapping is not None:
            brand = db.scalar(select(Brand).where(Brand.id == mapping.internal_resource_id))
        product.brand_id = (brand or sync_single_brand(db, company_id, remote)).id
        break


def sync_single_product(db: Session, company_id: str, item: dict) -> Product:
    external_id = str(item["id"])
    sku = item.get("sku")
    name = item["name"]
    price_minor = _price_string_to_minor(item.get("regular_price") or item.get("price"))
    sale_price_minor = (
        _price_string_to_minor(item.get("sale_price"))
        if item.get("sale_price") not in {None, ""}
        else None
    )
    vendor_id = extract_vendor_id_from_item(item)
    if vendor_id:
        vendor_exists = db.scalar(
            select(Vendor.id).where(
                Vendor.company_id == company_id,
                Vendor.id == vendor_id,
            )
        )
        if vendor_exists is None:
            vendor_id = None

    mapping = get_external_resource_map(
        db,
        company_id=company_id,
        resource_type="product",
        external_id=external_id,
    )
    product = None
    if mapping:
        product = db.scalar(
            select(Product).where(
                Product.company_id == company_id,
                Product.id == mapping.internal_resource_id,
            )
        )

    if product and vendor_id is None:
        vendor_product = db.scalar(
            select(VendorProduct).where(
                VendorProduct.company_id == company_id,
                VendorProduct.product_id == product.id,
            )
        )
        if vendor_product is not None:
            vendor_id = vendor_product.vendor_id

    if not product and sku:
        product = db.scalar(
            select(Product).where(Product.company_id == company_id, Product.sku == sku)
        )
        if product is None:
            variant = db.scalar(
                select(ProductVariant).where(
                    ProductVariant.company_id == company_id,
                    ProductVariant.sku == sku,
                )
            )
            if variant is not None:
                product = db.scalar(
                    select(Product).where(
                        Product.company_id == company_id,
                        Product.id == variant.product_id,
                    )
                )
        if product:
            upsert_external_resource_map(
                db,
                company_id=company_id,
                resource_type="product",
                internal_id=product.id,
                external_id=external_id,
            )

    vendor_managed_stock = bool(vendor_id)
    if product is not None:
        vendor_managed_stock = vendor_managed_stock or bool(product.vendor_id) or bool(
            db.scalar(
                select(VendorProduct.id).where(
                    VendorProduct.company_id == company_id,
                    VendorProduct.product_id == product.id,
                )
            )
        )

    if product:
        product.name = name
        product.slug = item.get("slug") or product.slug
        product.sku = sku or product.sku
        product.product_type = item.get("type") or product.product_type
        product.status = "active" if item.get("status") == "publish" else "draft"
        product.description = item.get("description") or product.description
        product.short_description = item.get("short_description") or product.short_description
        product.visibility = item.get("catalog_visibility") or product.visibility
        product.featured = bool(item.get("featured", product.featured))
        product.global_unique_id = item.get("global_unique_id") or product.global_unique_id
        product.regular_price_minor = price_minor
        product.sale_price_minor = sale_price_minor
        product.tax_status = item.get("tax_status") or product.tax_status
        product.tax_class = item.get("tax_class") or product.tax_class
        if not vendor_managed_stock:
            product.manage_stock = bool(item.get("manage_stock", product.manage_stock))
            product.stock_quantity = _parse_woo_stock_quantity(item)
            product.stock_status = item.get("stock_status") or product.stock_status
        product.backorders = item.get("backorders") or product.backorders
        product.sold_individually = bool(item.get("sold_individually", product.sold_individually))
        dimensions = item.get("dimensions") if isinstance(item.get("dimensions"), dict) else {}
        product.weight = item.get("weight") or product.weight
        product.length = dimensions.get("length") or product.length
        product.width = dimensions.get("width") or product.width
        product.height = dimensions.get("height") or product.height
        product.shipping_class = item.get("shipping_class") or product.shipping_class
        product.reviews_allowed = bool(item.get("reviews_allowed", product.reviews_allowed))
        product.purchase_note = item.get("purchase_note") or product.purchase_note
        if item.get("menu_order") is not None:
            product.menu_order = int(item.get("menu_order") or 0)
        if isinstance(item.get("attributes"), list):
            product.attributes = item["attributes"]
        if isinstance(item.get("default_attributes"), list):
            product.default_attributes = item["default_attributes"]
        if vendor_id:
            product.vendor_id = vendor_id
            vendor_product = db.scalar(
                select(VendorProduct).where(
                    VendorProduct.company_id == company_id,
                    VendorProduct.product_id == product.id,
                )
            )
            if vendor_product is None:
                db.add(
                    VendorProduct(
                        company_id=company_id,
                        vendor_id=vendor_id,
                        product_id=product.id,
                        approval_status="approved",
                        metadata_json={},
                    )
                )
            else:
                vendor_product.vendor_id = vendor_id
                if vendor_product.approval_status not in {"approved", "rejected"}:
                    vendor_product.approval_status = "approved"
        variants = db.scalars(
            select(ProductVariant).where(ProductVariant.product_id == product.id)
        ).all()
        for variant in variants:
            variant.price_minor = price_minor
            variant.sale_price_minor = sale_price_minor
    else:
        from erp.packages.core.catalog_services import create_product
        from erp.packages.core.schemas import (
            ProductCreate,
            ProductVariantCreate,
        )

        dimensions = item.get("dimensions") if isinstance(item.get("dimensions"), dict) else {}

        payload = ProductCreate(
            name=name,
            sku=None,
            vendor_id=vendor_id,
            product_type=item.get("type") or "simple",
            status="active" if item.get("status") == "publish" else "draft",
            description=item.get("description"),
            short_description=item.get("short_description"),
            visibility=item.get("catalog_visibility") or "visible",
            featured=bool(item.get("featured", False)),
            global_unique_id=item.get("global_unique_id"),
            regular_price_minor=price_minor,
            sale_price_minor=sale_price_minor,
            tax_status=item.get("tax_status") or "taxable",
            tax_class=item.get("tax_class") or None,
            manage_stock=bool(item.get("manage_stock", False)) if not vendor_managed_stock else True,
            stock_quantity=_parse_woo_stock_quantity(item) if not vendor_managed_stock else None,
            stock_status=(item.get("stock_status") or "instock") if not vendor_managed_stock else "outofstock",
            backorders=item.get("backorders") or "no",
            sold_individually=bool(item.get("sold_individually", False)),
            weight=item.get("weight") or None,
            length=dimensions.get("length") or None,
            width=dimensions.get("width") or None,
            height=dimensions.get("height") or None,
            shipping_class=item.get("shipping_class") or None,
            reviews_allowed=bool(item.get("reviews_allowed", True)),
            purchase_note=item.get("purchase_note") or None,
            menu_order=int(item.get("menu_order") or 0),
            attributes=item.get("attributes") if isinstance(item.get("attributes"), list) else [],
            default_attributes=(
                item.get("default_attributes")
                if isinstance(item.get("default_attributes"), list)
                else []
            ),
            variants=[
                ProductVariantCreate(
                    sku=sku or f"WC-AUTO-{new_uuid()[:8]}",
                    price_minor=price_minor,
                    sale_price_minor=sale_price_minor,
                )
            ],
            images=[],
        )
        product = create_product(
            db,
            company_id=company_id,
            user_id=woocommerce_sync_user_id(db, company_id),
            payload=payload,
        )
        upsert_external_resource_map(
            db,
            company_id=company_id,
            resource_type="product",
            internal_id=product.id,
            external_id=external_id,
        )

    apply_product_taxonomies_from_woocommerce(db, company_id=company_id, product=product, item=item)
    reconcile_product_images_from_remote(
        db,
        company_id=company_id,
        product=product,
        remote_images=_remote_product_images(item),
    )

    sync_product_stock_from_woocommerce(
        db,
        company_id=company_id,
        product=product,
        item=item,
    )
    db.flush()
    return product


def sync_single_customer(db: Session, company_id: str, item: dict) -> Customer:
    external_id = str(item["id"])
    email = item.get("email")
    first_name = item.get("first_name", "")
    last_name = item.get("last_name", "")
    full_name = f"{first_name} {last_name}".strip() or email or f"Woo Customer {external_id}"

    billing = item.get("billing", {})
    phone = billing.get("phone") or item.get("username")

    mapping = get_external_resource_map(
        db,
        company_id=company_id,
        resource_type="customer",
        external_id=external_id,
    )
    customer = None
    if mapping:
        customer = db.scalar(
            select(Customer).where(
                Customer.company_id == company_id,
                Customer.id == mapping.internal_resource_id,
            )
        )

    if not customer and email:
        customer = db.scalar(
            select(Customer).where(Customer.company_id == company_id, Customer.email == email)
        )
        if customer:
            upsert_external_resource_map(
                db,
                company_id=company_id,
                resource_type="customer",
                internal_id=customer.id,
                external_id=external_id,
            )

    if customer:
        customer.full_name = full_name
        if email:
            customer.email = email
        if phone:
            customer.phone = phone
    else:
        from erp.packages.core.customer_services import create_customer
        from erp.packages.core.schemas import CustomerCreate

        payload = CustomerCreate(
            full_name=full_name,
            email=email,
            phone=phone,
        )
        customer = create_customer(
            db,
            company_id=company_id,
            user_id=woocommerce_sync_user_id(db, company_id),
            payload=payload,
        )
        upsert_external_resource_map(
            db,
            company_id=company_id,
            resource_type="customer",
            internal_id=customer.id,
            external_id=external_id,
        )

    if billing and billing.get("address_1"):
        from erp.packages.core.customer_services import add_customer_address
        from erp.packages.core.schemas import CustomerAddressCreate

        existing_addresses = db.scalars(
            select(CustomerAddress).where(CustomerAddress.customer_id == customer.id)
        ).all()
        if not existing_addresses:
            addr_payload = CustomerAddressCreate(
                line1=billing.get("address_1", ""),
                line2=billing.get("address_2"),
                city=billing.get("city"),
                state=billing.get("state"),
                postal_code=billing.get("postcode"),
                country=billing.get("country") or "PK",
                recipient_name=full_name,
                phone=phone,
                label="Billing",
                is_default=True,
            )
            add_customer_address(
                db,
                company_id=company_id,
                user_id=woocommerce_sync_user_id(db, company_id),
                customer_id=customer.id,
                payload=addr_payload,
            )

    db.flush()
    return customer


def sync_single_order(db: Session, company_id: str, item: dict) -> Order:
    external_id = str(item["id"])

    mapping = get_external_resource_map(
        db,
        company_id=company_id,
        resource_type="order",
        external_id=external_id,
    )
    order = None
    if mapping:
        order = db.scalar(
            select(Order).where(
                Order.company_id == company_id,
                Order.id == mapping.internal_resource_id,
            )
        )

    if order:
        order.sales_channel = "woocommerce"
        order.order_source = "woocommerce"
        order.external_order_id = external_id
        apply_woocommerce_order_status(
            db,
            company_id=company_id,
            order=order,
            woo_status=item.get("status"),
        )
    else:
        cust_external_id = str(item.get("customer_id") or 0)
        customer = None
        if cust_external_id != "0":
            cust_map = get_external_resource_map(
                db,
                company_id=company_id,
                resource_type="customer",
                external_id=cust_external_id,
            )
            if cust_map:
                customer = db.scalar(
                    select(Customer).where(
                        Customer.company_id == company_id,
                        Customer.id == cust_map.internal_resource_id,
                    )
                )

        billing = item.get("billing", {})
        email = billing.get("email")
        if not customer and email:
            customer = db.scalar(
                select(Customer).where(
                    Customer.company_id == company_id,
                    Customer.email == email,
                )
            )

        if not customer:
            from erp.packages.core.customer_services import create_customer
            from erp.packages.core.schemas import CustomerCreate

            c_name = (
                f"{billing.get('first_name', '')} {billing.get('last_name', '')}".strip()
                or email
                or f"Woo Order Customer {external_id}"
            )
            customer = create_customer(
                db,
                company_id=company_id,
                user_id=woocommerce_sync_user_id(db, company_id),
                payload=CustomerCreate(
                    full_name=c_name,
                    email=email,
                    phone=billing.get("phone"),
                ),
            )
            if cust_external_id != "0":
                upsert_external_resource_map(
                    db,
                    company_id=company_id,
                    resource_type="customer",
                    internal_id=customer.id,
                    external_id=cust_external_id,
                )

        from erp.packages.core.schemas import OrderCreate, OrderItemCreate

        order_items_payload = []
        for line in item.get("line_items", []):
            line_prod_id = str(line["product_id"])
            line_var_id = str(line.get("variation_id") or 0)

            v_map = None
            if line_var_id != "0":
                v_map = get_external_resource_map(
                    db,
                    company_id=company_id,
                    resource_type="product",
                    external_id=line_var_id,
                )
            if not v_map:
                v_map = get_external_resource_map(
                    db,
                    company_id=company_id,
                    resource_type="product",
                    external_id=line_prod_id,
                )

            product_id = None
            variant_id = None
            if v_map:
                if line_var_id != "0":
                    v_row = db.scalar(
                        select(ProductVariant).where(
                            ProductVariant.id == v_map.internal_resource_id
                        )
                    )
                    if v_row:
                        variant_id = v_row.id
                        product_id = v_row.product_id
                else:
                    product_id = v_map.internal_resource_id
                    v_row = db.scalar(
                        select(ProductVariant).where(
                            ProductVariant.product_id == v_map.internal_resource_id
                        )
                    )
                    if v_row:
                        variant_id = v_row.id

            if not variant_id and line.get("sku"):
                v_row = db.scalar(
                    select(ProductVariant).where(
                        ProductVariant.company_id == company_id,
                        ProductVariant.sku == line["sku"],
                    )
                )
                if v_row:
                    variant_id = v_row.id
                    product_id = v_row.product_id

            if not variant_id:
                from erp.packages.core.catalog_services import create_product
                from erp.packages.core.schemas import ProductCreate, ProductVariantCreate

                p_create = ProductCreate(
                    name=line["name"],
                    sku=None,
                    variants=[
                        ProductVariantCreate(
                            sku=line.get("sku") or f"WC-AUTO-{new_uuid()[:8]}",
                            price_minor=int(float(line.get("price") or 0) * 100),
                        )
                    ],
                )
                p_new = create_product(
                    db,
                    company_id=company_id,
                    user_id=woocommerce_sync_user_id(db, company_id),
                    payload=p_create,
                )
                upsert_external_resource_map(
                    db,
                    company_id=company_id,
                    resource_type="product",
                    internal_id=p_new.id,
                    external_id=line_prod_id,
                )
                v_row = db.scalar(
                    select(ProductVariant).where(ProductVariant.product_id == p_new.id)
                )
                product_id = p_new.id
                variant_id = v_row.id
                if line_var_id != "0":
                    upsert_external_resource_map(
                        db,
                        company_id=company_id,
                        resource_type="product",
                        internal_id=v_row.id,
                        external_id=line_var_id,
                    )

            order_items_payload.append(
                OrderItemCreate(
                    product_id=product_id,
                    variant_id=variant_id,
                    quantity=line["quantity"],
                    unit_price_minor=int(float(line["price"] or 0) * 100),
                )
            )

        from erp.packages.core.order_services import create_order

        disc = int(float(item.get("discount_total") or 0) * 100)
        tax = int(float(item.get("total_tax") or 0) * 100)
        ship = int(float(item.get("shipping_total") or 0) * 100)

        order_create_payload = OrderCreate(
            customer_id=customer.id,
            currency=item.get("currency") or "PKR",
            discount_minor=disc,
            tax_minor=tax,
            shipping_minor=ship,
            notes=item.get("customer_note"),
            items=order_items_payload,
        )

        order = create_order(
            db,
            company_id=company_id,
            user_id=woocommerce_sync_user_id(db, company_id),
            payload=order_create_payload,
        )
        order.order_number = f"WC-{item['number']}"
        order.sales_channel = "woocommerce"
        order.order_source = "woocommerce"
        order.external_order_id = external_id
        upsert_external_resource_map(
            db,
            company_id=company_id,
            resource_type="order",
            internal_id=order.id,
            external_id=external_id,
        )

        woo_status = item.get("status")
        apply_woocommerce_order_status(
            db,
            company_id=company_id,
            order=order,
            woo_status=woo_status,
        )

        if woo_status in {"processing", "completed"}:
            from erp.packages.core.order_services import record_payment
            from erp.packages.core.schemas import PaymentCreate

            payment_payload = PaymentCreate(
                amount_minor=int(float(item["total"] or 0) * 100),
                currency=item.get("currency") or "PKR",
                method=item.get("payment_method") or "cash",
                reference=item.get("transaction_id"),
                status="paid",
            )
            record_payment(
                db,
                company_id=company_id,
                user_id=woocommerce_sync_user_id(db, company_id),
                order_id=order.id,
                payload=payment_payload,
            )

    # The same source order can arrive through a webhook and the scheduled
    # pull. The stock helper is idempotent through reservation_status and keeps
    # vendor stock in the Vendor Shop warehouse rather than WooCommerce's
    # legacy reference warehouse.
    if order.status == "cancelled":
        restore_cancelled_woocommerce_order_stock(
            db, company_id=company_id, order=order
        )
    elif order.status != "refunded":
        deduct_woocommerce_order_stock(db, company_id=company_id, order=order)

    db.flush()
    return order


def pull_woocommerce_collection(
    db: Session,
    company_id: str,
    *,
    resource_path: str,
    action: str,
    allow_missing: bool = False,
    progress_callback: Callable[[], None] | None = None,
) -> list[dict]:
    """Read WooCommerce pages while renewing the durable job between requests."""

    items: list[dict] = []
    page = 1
    per_page = 100
    while True:
        result = make_woocommerce_request(
            db,
            company_id,
            "GET",
            resource_path,
            params={"per_page": per_page, "page": page},
        )
        response = result.response
        if allow_missing and response.status_code == 404:
            # Brands is optional in WooCommerce and some hosts restrict the
            # taxonomy routes. Product sync still imports any embedded terms.
            return []
        if response.status_code != 200:
            raise ServiceError(
                502,
                format_remote_http_error(action=action, result=result),
            )
        page_items = response.json()
        if not isinstance(page_items, list):
            raise ServiceError(
                502,
                f"{action} failed because WooCommerce returned a non-list response.",
            )
        items.extend(item for item in page_items if isinstance(item, dict))
        # The callback commits the short checkpoint in the durable worker,
        # which renews both the database lease and the worker heartbeat before
        # the next potentially slow remote page is requested.
        if progress_callback is not None:
            progress_callback()
        if len(page_items) < per_page:
            break
        page += 1
    return items


def _checkpoint_pulled_records(
    pulled: int,
    progress_callback: Callable[[], None] | None,
) -> None:
    if progress_callback is not None and pulled > 0 and pulled % SYNC_PULL_PROGRESS_BATCH_SIZE == 0:
        progress_callback()


def _finalize_pulled_record_checkpoints(
    pulled: int,
    progress_callback: Callable[[], None] | None,
) -> None:
    if progress_callback is not None and pulled > 0 and pulled % SYNC_PULL_PROGRESS_BATCH_SIZE != 0:
        progress_callback()


def _mapped_internal_resource_exists(
    db: Session,
    *,
    company_id: str,
    resource_type: str,
    external_id: str,
    model,
) -> bool:
    mapping = get_external_resource_map(
        db,
        company_id=company_id,
        resource_type=resource_type,
        external_id=external_id,
    )
    if mapping is None:
        return False
    return (
        db.scalar(
            select(model.id).where(
                model.company_id == company_id,
                model.id == mapping.internal_resource_id,
            )
        )
        is not None
    )


def _woocommerce_product_exists(db: Session, company_id: str, item: dict) -> bool:
    external_id = str(item["id"])
    if _mapped_internal_resource_exists(
        db,
        company_id=company_id,
        resource_type="product",
        external_id=external_id,
        model=Product,
    ):
        return True
    sku = item.get("sku")
    if not sku:
        return False
    if db.scalar(select(Product.id).where(Product.company_id == company_id, Product.sku == sku)):
        return True
    return (
        db.scalar(
            select(ProductVariant.id).where(
                ProductVariant.company_id == company_id,
                ProductVariant.sku == sku,
            )
        )
        is not None
    )


def _woocommerce_customer_exists(db: Session, company_id: str, item: dict) -> bool:
    external_id = str(item["id"])
    if _mapped_internal_resource_exists(
        db,
        company_id=company_id,
        resource_type="customer",
        external_id=external_id,
        model=Customer,
    ):
        return True
    email = item.get("email")
    if not email:
        return False
    return (
        db.scalar(
            select(Customer.id).where(
                Customer.company_id == company_id,
                Customer.email == email,
            )
        )
        is not None
    )


def _woocommerce_order_exists(db: Session, company_id: str, item: dict) -> bool:
    return _mapped_internal_resource_exists(
        db,
        company_id=company_id,
        resource_type="order",
        external_id=str(item["id"]),
        model=Order,
    )


def _pull_incremental_woocommerce_collection(
    db: Session,
    company_id: str,
    *,
    resource_type: str,
    resource_path: str,
    action: str,
    sync_item: Callable[[Session, str, dict], object],
    existing_item: Callable[[Session, str, dict], bool],
    force_full: bool = False,
    item_filter: Callable[[Session, str, dict], bool] | None = None,
    persist_checkpoint: bool = True,
    progress_callback: Callable[[], None] | None = None,
) -> dict[str, int]:
    """Download and process one inbound collection page at a time."""

    sync_started_at = utcnow()
    checkpoint_supported = resource_type in WOOCOMMERCE_LAST_SYNC_KEYS
    last_sync = get_woocommerce_last_sync(db, company_id, resource_type)
    incremental = checkpoint_supported and last_sync is not None and not force_full
    plural = f"{resource_type}s"
    LOGGER.info(
        "Starting %s sync for %s. Last sync: %s",
        "incremental" if incremental else "full",
        plural,
        _woocommerce_timestamp_for_log(last_sync),
    )
    LOGGER.info(
        "Downloading %s%s...",
        "modified " if incremental else "all ",
        plural,
    )

    downloaded = 0
    pulled = 0
    created = 0
    updated = 0
    skipped = 0
    page = 1
    per_page = 100
    try:
        while True:
            params: dict[str, object] = {
                "per_page": per_page,
                "page": page,
                "order": "asc",
                "orderby": "id",
            }
            if incremental:
                params.update(
                    {
                        "modified_after": _woocommerce_incremental_after(last_sync),
                        "modified_before": _woocommerce_second_precision_boundary(
                            sync_started_at,
                            upper=True,
                        ),
                        "dates_are_gmt": "true",
                        "orderby": "modified",
                    }
                )
            result = make_woocommerce_request(
                db,
                company_id,
                "GET",
                resource_path,
                params=params,
            )
            response = result.response
            if response.status_code != 200:
                raise ServiceError(
                    502,
                    format_remote_http_error(action=action, result=result),
                )
            page_items = response.json()
            if not isinstance(page_items, list):
                raise ServiceError(
                    502,
                    f"{action} failed because WooCommerce returned a non-list response.",
                )
            downloaded += len(page_items)
            for item in page_items:
                if not isinstance(item, dict):
                    skipped += 1
                    continue
                if item_filter is not None and not item_filter(db, company_id, item):
                    skipped += 1
                    continue
                existed = existing_item(db, company_id, item)
                sync_item(db, company_id, item)
                pulled += 1
                if existed:
                    updated += 1
                else:
                    created += 1

            # Flush the complete page before its existing durable-worker
            # checkpoint commits. A failure therefore never commits a partial
            # item, and the last-sync timestamp remains unchanged.
            db.flush()
            if progress_callback is not None:
                progress_callback()
            if len(page_items) < per_page:
                break
            page += 1

        new_timestamp = None
        if checkpoint_supported and persist_checkpoint:
            new_timestamp = store_woocommerce_last_sync(
                db,
                company_id=company_id,
                resource_type=resource_type,
                sync_started_at=sync_started_at,
            )
    except Exception:
        LOGGER.exception(
            "%s failed. Previous timestamp preserved: %s",
            action,
            _woocommerce_timestamp_for_log(last_sync),
        )
        raise

    LOGGER.info("Downloaded: %s %s", downloaded, plural)
    LOGGER.info("Updated: %s", updated)
    LOGGER.info("Created: %s", created)
    LOGGER.info("Skipped: %s", skipped)
    if new_timestamp is not None:
        LOGGER.info(
            "Finished successfully. New timestamp: %s",
            _woocommerce_timestamp_for_log(new_timestamp),
        )
    else:
        LOGGER.info("Finished successfully. This WooCommerce endpoint uses full synchronization.")
    return {"pulled": pulled}


def pull_categories(
    db: Session, company_id: str, *, progress_callback: Callable[[], None] | None = None
) -> dict[str, int]:
    items = pull_woocommerce_collection(
        db,
        company_id,
        resource_path="/products/categories",
        action="Pull categories",
        progress_callback=progress_callback,
        allow_missing=True,
    )
    for item in items:
        sync_single_category(db, company_id, item)
    for item in items:
        if not item.get("parent"):
            continue
        child_map = get_external_resource_map(
            db, company_id=company_id, resource_type="category", external_id=str(item["id"])
        )
        parent_map = get_external_resource_map(
            db, company_id=company_id, resource_type="category", external_id=str(item["parent"])
        )
        if child_map and parent_map:
            child = db.get(Category, child_map.internal_resource_id)
            if child is not None:
                child.parent_id = parent_map.internal_resource_id
    _finalize_pulled_record_checkpoints(len(items), progress_callback)
    return {"pulled": len(items)}


def pull_brands(
    db: Session, company_id: str, *, progress_callback: Callable[[], None] | None = None
) -> dict[str, int]:
    items = pull_woocommerce_collection(
        db,
        company_id,
        resource_path="/products/brands",
        action="Pull brands",
        progress_callback=progress_callback,
        allow_missing=True,
    )
    for item in items:
        sync_single_brand(db, company_id, item)
    _finalize_pulled_record_checkpoints(len(items), progress_callback)
    return {"pulled": len(items)}


def pull_products(
    db: Session,
    company_id: str,
    *,
    progress_callback: Callable[[], None] | None = None,
    archive_missing: bool = False,
    force_full: bool = False,
    vendor_id: str | None = None,
) -> dict[str, int]:
    item_filter = None
    if vendor_id:
        def vendor_item_filter(session: Session, scoped_company_id: str, item: dict) -> bool:
            return product_belongs_to_vendor(
                session,
                company_id=scoped_company_id,
                item=item,
                vendor_id=vendor_id,
            )

        item_filter = vendor_item_filter
    result = _pull_incremental_woocommerce_collection(
        db,
        company_id,
        resource_type="product",
        resource_path="/products",
        action="Pull products",
        sync_item=sync_single_product,
        existing_item=_woocommerce_product_exists,
        force_full=force_full,
        item_filter=item_filter,
        persist_checkpoint=vendor_id is None,
        progress_callback=progress_callback,
    )
    if archive_missing:
        reconcile_products(db, company_id, progress_callback=progress_callback)
    return result


def archive_missing_remote_product_ids(
    db: Session,
    company_id: str,
    remote_ids: set[str],
) -> int:
    mappings = db.scalars(
        select(ExternalResourceMap).where(
            ExternalResourceMap.company_id == company_id,
            ExternalResourceMap.connector == CONNECTOR,
            ExternalResourceMap.internal_resource_type == "product",
            ExternalResourceMap.external_resource_type == "product",
        )
    ).all()
    archived = 0
    for mapping in mappings:
        if mapping.external_resource_id in remote_ids:
            continue
        product = db.scalar(
            select(Product).where(
                Product.company_id == company_id,
                Product.id == mapping.internal_resource_id,
            )
        )
        if product is None or product.status == "archived":
            continue
        archive_product(
            db,
            company_id=company_id,
            user_id=woocommerce_sync_user_id(db, company_id),
            product_id=product.id,
        )
        archived += 1
    return archived


def archive_missing_remote_products(
    db: Session,
    company_id: str,
    remote_products: list[dict],
) -> int:
    remote_ids = {
        str(product["id"])
        for product in remote_products
        if isinstance(product, dict) and product.get("id") is not None
    }
    return archive_missing_remote_product_ids(db, company_id, remote_ids)


def reconcile_products(
    db: Session,
    company_id: str,
    *,
    progress_callback: Callable[[], None] | None = None,
) -> dict[str, int]:
    """Verify mapped products against a full remote ID-only listing."""

    LOGGER.info("Starting WooCommerce product reconciliation (full ID scan).")
    remote_ids: set[str] = set()
    skipped = 0
    page = 1
    per_page = 100
    try:
        while True:
            result = make_woocommerce_request(
                db,
                company_id,
                "GET",
                "/products",
                params={
                    "per_page": per_page,
                    "page": page,
                    "_fields": "id",
                    "orderby": "id",
                    "order": "asc",
                },
            )
            response = result.response
            if response.status_code != 200:
                raise ServiceError(
                    502,
                    format_remote_http_error(action="Reconcile products", result=result),
                )
            page_items = response.json()
            if not isinstance(page_items, list):
                raise ServiceError(
                    502,
                    "Product reconciliation failed because WooCommerce returned "
                    "a non-list response.",
                )
            for item in page_items:
                if not isinstance(item, dict) or item.get("id") is None:
                    skipped += 1
                    continue
                remote_ids.add(str(item["id"]))
            if progress_callback is not None:
                progress_callback()
            if len(page_items) < per_page:
                break
            page += 1

        archived = archive_missing_remote_product_ids(db, company_id, remote_ids)
        db.flush()
    except Exception:
        LOGGER.exception("WooCommerce product reconciliation failed; no products were archived.")
        raise

    LOGGER.info(
        "Product reconciliation finished successfully. Remote IDs: %s; archived: %s; skipped: %s",
        len(remote_ids),
        archived,
        skipped,
    )
    return {"remote_ids": len(remote_ids), "archived": archived, "skipped": skipped}


def pull_customers(
    db: Session,
    company_id: str,
    *,
    progress_callback: Callable[[], None] | None = None,
) -> dict[str, int]:
    # wc/v3 customers does not support modified_after. Unknown request
    # parameters are not applied by WC_REST_Customers_Controller, so sending a
    # saved timestamp would silently behave like an unfiltered full pull.
    result = _pull_incremental_woocommerce_collection(
        db,
        company_id,
        resource_type="customer",
        resource_path="/customers",
        action="Pull customers",
        sync_item=sync_single_customer,
        existing_item=_woocommerce_customer_exists,
        progress_callback=progress_callback,
    )
    # Remove checkpoints written by versions which incorrectly treated the
    # customer endpoint as incremental. The merge preserves every other key.
    update_woocommerce_setting_value(
        db,
        company_id=company_id,
        updates={WOOCOMMERCE_LEGACY_CUSTOMER_SYNC_KEY: None},
    )
    return result


def pull_orders(
    db: Session,
    company_id: str,
    *,
    progress_callback: Callable[[], None] | None = None,
    force_full: bool = False,
) -> dict[str, int]:
    return _pull_incremental_woocommerce_collection(
        db,
        company_id,
        resource_type="order",
        resource_path="/orders",
        action="Pull orders",
        sync_item=sync_single_order,
        existing_item=_woocommerce_order_exists,
        force_full=force_full,
        progress_callback=progress_callback,
    )


def _sync_outbox_operation_priority(record: SyncOutbox) -> tuple[int, object, str]:
    if record.resource_type == "product" and record.operation == "push":
        priority = 0
    elif record.resource_type == "product" and record.operation == "push_media":
        priority = 1
    elif record.resource_type == "product" and record.operation == "push_videos":
        priority = 2
    else:
        priority = 3
    return (priority, record.created_at, record.id)


def _sync_outbox_record_belongs_to_vendor(
    db: Session,
    *,
    company_id: str,
    record: SyncOutbox,
    vendor_id: str,
) -> bool:
    if record.resource_type == "product":
        return product_belongs_to_vendor(
            db,
            company_id=company_id,
            product_id=record.resource_id,
            vendor_id=vendor_id,
        )
    if record.resource_type == "stock" and record.resource_id:
        variant = db.scalar(
            select(ProductVariant).where(
                ProductVariant.company_id == company_id,
                ProductVariant.id == record.resource_id,
            )
        )
        return bool(
            variant
            and product_belongs_to_vendor(
                db,
                company_id=company_id,
                product_id=variant.product_id,
                vendor_id=vendor_id,
            )
        )
    return False


def _pending_sync_outbox_records(
    db: Session, company_id: str, *, vendor_id: str | None = None
) -> list[SyncOutbox]:
    now = utcnow()
    records = db.scalars(
        select(SyncOutbox).where(
            SyncOutbox.company_id == company_id,
            SyncOutbox.connector == CONNECTOR,
            SyncOutbox.status.in_({"pending", "failed"}),
            SyncOutbox.attempts < SYNC_OUTBOX_MAX_ATTEMPTS,
            (SyncOutbox.next_attempt_at.is_(None)) | (SyncOutbox.next_attempt_at <= now),
        )
    ).all()
    if vendor_id:
        records = [
            record
            for record in records
            if _sync_outbox_record_belongs_to_vendor(
                db,
                company_id=company_id,
                record=record,
                vendor_id=vendor_id,
            )
        ]
    return sorted(records, key=_sync_outbox_operation_priority)


def find_existing_woocommerce_product(
    db: Session,
    *,
    company_id: str,
    product: Product,
) -> str | None:
    """Find a remote product after an interrupted create before retrying it.

    WooCommerce does not give this client a generic idempotency header.  A
    retry first checks SKU, then slug, so a worker crash after a successful
    remote create can recover the mapping without creating a duplicate.
    """

    params: dict[str, object] | None = None
    if product.sku:
        params = {"sku": product.sku}
    elif product.slug:
        params = {"slug": product.slug}
    if params is None:
        return None
    result = make_woocommerce_request(
        db,
        company_id,
        "GET",
        "/products",
        params=params,
    )
    if result.response.status_code == 404:
        return None
    if result.response.status_code != 200:
        raise ServiceError(
            502,
            format_remote_http_error(action="Recover product create", result=result),
        )
    payload = result.response.json()
    if not isinstance(payload, list):
        raise ServiceError(502, "WooCommerce product lookup returned an invalid payload.")
    for item in payload:
        if isinstance(item, dict) and item.get("id") is not None:
            return str(item["id"])
    return None


def is_invalid_woocommerce_product_id(result: WooCommerceRequestResult) -> bool:
    """Return true only for WooCommerce's safe-to-recover stale-ID response."""
    if result.response.status_code != 400:
        return False
    try:
        payload = result.response.json()
    except ValueError:
        return False
    if not isinstance(payload, dict):
        return False
    return payload.get("code") == "woocommerce_rest_product_invalid_id"


def mark_superseded_outbox_records_synced(
    db: Session,
    *,
    company_id: str,
    operation: str,
    resource_type: str,
    resource_id: str,
    current_record_id: str,
) -> None:
    records = db.scalars(
        select(SyncOutbox).where(
            SyncOutbox.company_id == company_id,
            SyncOutbox.connector == CONNECTOR,
            SyncOutbox.operation == operation,
            SyncOutbox.resource_type == resource_type,
            SyncOutbox.resource_id == resource_id,
            SyncOutbox.id != current_record_id,
            SyncOutbox.status.in_({"pending", "failed", "processing"}),
        )
    ).all()
    for record in records:
        record.status = "synced"
        record.last_error = None
        record.next_attempt_at = None
    if records:
        db.flush()


def process_sync_outbox(
    db: Session,
    company_id: str,
    *,
    vendor_id: str | None = None,
    checkpoint: Callable[[], None] | None = None,
) -> dict[str, int]:
    from erp.packages.core.inventory_services import stock_levels

    pushed = 0
    pushed_media = 0
    pushed_videos = 0
    failed = 0
    deferred = 0
    deferred_videos = 0
    processed_ids: set[str] = set()

    def checkpoint_record() -> None:
        # Persist one small checkpoint at a time. In the durable worker path
        # ``checkpoint`` commits the change and renews the sync-job lease;
        # legacy callers still get a real commit here so an outbox claim
        # survives a process crash before a remote request completes.
        db.flush()
        if checkpoint is not None:
            checkpoint()
        else:
            db.commit()

    def claim_record_for_remote_work(rec: SyncOutbox) -> None:
        """Durably claim an outbox row before performing any remote I/O.

        A worker can die after WooCommerce accepts a request but before the
        result is checkpointed. Persisting the attempt and ``processing``
        state first makes stale-record recovery retry it with ``attempts > 1``;
        product creation then performs the SKU/slug recovery lookup rather
        than issuing a duplicate POST.
        """

        rec.attempts += 1
        rec.status = "processing"
        rec.last_error = None
        rec.next_attempt_at = None
        checkpoint_record()

    while True:
        records = [
            record
            for record in _pending_sync_outbox_records(
                db, company_id, vendor_id=vendor_id
            )
            if record.id not in processed_ids
        ]
        if not records:
            break

        for rec in records:
            if rec.status not in {"pending", "failed"}:
                processed_ids.add(rec.id)
                continue
            processed_ids.add(rec.id)
            claim_record_for_remote_work(rec)
            try:
                if rec.resource_type == "product" and rec.operation == "push":
                    product = db.scalar(
                        select(Product).where(
                            Product.company_id == company_id,
                            Product.id == rec.resource_id,
                        )
                    )
                    if product:
                        mapping = db.scalar(
                            select(ExternalResourceMap).where(
                                ExternalResourceMap.company_id == company_id,
                                ExternalResourceMap.connector == CONNECTOR,
                                ExternalResourceMap.internal_resource_type == "product",
                                ExternalResourceMap.internal_resource_id == product.id,
                            )
                        )
                        if mapping is None and rec.attempts > 1:
                            recovered_external_id = find_existing_woocommerce_product(
                                db,
                                company_id=company_id,
                                product=product,
                            )
                            if recovered_external_id is not None:
                                mapping = upsert_external_resource_map(
                                    db,
                                    company_id=company_id,
                                    resource_type="product",
                                    internal_id=product.id,
                                    external_id=recovered_external_id,
                                )
                        payload = build_woocommerce_product_payload(db, product)
                        if mapping:
                            res = make_woocommerce_request(
                                db,
                                company_id,
                                "PUT",
                                f"/products/{mapping.external_resource_id}",
                                payload,
                            )
                            if is_invalid_woocommerce_product_id(res):
                                # The remote product was deleted or the old
                                # mapping belonged to another store. Recover by
                                # SKU/slug before creating a replacement.
                                db.delete(mapping)
                                db.flush()
                                recovered_external_id = find_existing_woocommerce_product(
                                    db,
                                    company_id=company_id,
                                    product=product,
                                )
                                if recovered_external_id is not None:
                                    mapping = upsert_external_resource_map(
                                        db,
                                        company_id=company_id,
                                        resource_type="product",
                                        internal_id=product.id,
                                        external_id=recovered_external_id,
                                    )
                                    res = make_woocommerce_request(
                                        db,
                                        company_id,
                                        "PUT",
                                        f"/products/{mapping.external_resource_id}",
                                        payload,
                                    )
                                else:
                                    res = make_woocommerce_request(
                                        db, company_id, "POST", "/products", payload
                                    )
                                    if res.response.status_code in {200, 201}:
                                        upsert_external_resource_map(
                                            db,
                                            company_id=company_id,
                                            resource_type="product",
                                            internal_id=product.id,
                                            external_id=str(res.response.json()["id"]),
                                        )
                        else:
                            res = make_woocommerce_request(
                                db,
                                company_id,
                                "POST",
                                "/products",
                                payload,
                            )
                            if res.response.status_code in {200, 201}:
                                ext_id = str(res.response.json()["id"])
                                upsert_external_resource_map(
                                    db,
                                    company_id=company_id,
                                    resource_type="product",
                                    internal_id=product.id,
                                    external_id=ext_id,
                                )
                        if res.response.status_code not in {200, 201}:
                            raise ServiceError(
                                502,
                                format_remote_http_error(action="Push product", result=res),
                            )
                        if product_requires_media_sync(
                            db,
                            company_id=company_id,
                            product=product,
                        ):
                            enqueue_product_media_sync(
                                db,
                                company_id=company_id,
                                product=product,
                            )
                        pushed += 1
                        mark_superseded_outbox_records_synced(
                            db,
                            company_id=company_id,
                            operation=rec.operation,
                            resource_type=rec.resource_type,
                            resource_id=rec.resource_id,
                            current_record_id=rec.id,
                        )

                elif rec.resource_type == "product" and rec.operation == "push_media":
                    product = db.scalar(
                        select(Product).where(
                            Product.company_id == company_id,
                            Product.id == rec.resource_id,
                        )
                    )
                    if product:
                        mapping = db.scalar(
                            select(ExternalResourceMap).where(
                                ExternalResourceMap.company_id == company_id,
                                ExternalResourceMap.connector == CONNECTOR,
                                ExternalResourceMap.internal_resource_type == "product",
                                ExternalResourceMap.internal_resource_id == product.id,
                            )
                        )
                        if mapping is None:
                            rec.attempts = max(0, rec.attempts - 1)
                            rec.status = "pending"
                            rec.next_attempt_at = utcnow() + timedelta(minutes=1)
                            rec.last_error = (
                                "Waiting for WooCommerce product sync before media sync."
                            )
                            deferred += 1
                            checkpoint_record()
                            continue
                        images_payload = build_woocommerce_product_media_payload(
                            db,
                            company_id=company_id,
                            product=product,
                            external_product_id=mapping.external_resource_id,
                            checkpoint=checkpoint_record,
                        )
                        res = make_woocommerce_request(
                            db,
                            company_id,
                            "PUT",
                            f"/products/{mapping.external_resource_id}",
                            {"images": images_payload},
                        )
                        if res.response.status_code not in {200, 201}:
                            raise ServiceError(
                                502,
                                format_remote_http_error(action="Push product media", result=res),
                            )
                        payload = res.response.json()
                        if not isinstance(payload, dict):
                            raise ServiceError(
                                502,
                                "WooCommerce product media update returned an invalid payload.",
                            )
                        reconcile_product_images_from_remote(
                            db,
                            company_id=company_id,
                            product=product,
                            remote_images=_remote_product_images(payload),
                        )
                        pushed_media += 1
                        mark_superseded_outbox_records_synced(
                            db,
                            company_id=company_id,
                            operation=rec.operation,
                            resource_type=rec.resource_type,
                            resource_id=rec.resource_id,
                            current_record_id=rec.id,
                        )

                elif rec.resource_type == "product" and rec.operation == "push_videos":
                    product = db.scalar(
                        select(Product).where(
                            Product.company_id == company_id,
                            Product.id == rec.resource_id,
                        )
                    )
                    if product:
                        mapping = db.scalar(
                            select(ExternalResourceMap).where(
                                ExternalResourceMap.company_id == company_id,
                                ExternalResourceMap.connector == CONNECTOR,
                                ExternalResourceMap.internal_resource_type == "product",
                                ExternalResourceMap.internal_resource_id == product.id,
                            )
                        )
                        if mapping is None:
                            rec.attempts = max(0, rec.attempts - 1)
                            rec.status = "pending"
                            rec.next_attempt_at = utcnow() + timedelta(minutes=1)
                            rec.last_error = (
                                "Waiting for WooCommerce product sync before video sync."
                            )
                            deferred_videos += 1
                            checkpoint_record()
                            continue
                        manifest = build_woocommerce_product_video_manifest(
                            db,
                            company_id=company_id,
                            product=product,
                            checkpoint=checkpoint_record,
                        )
                        res = make_woocommerce_request(
                            db,
                            company_id,
                            "PUT",
                            f"/products/{mapping.external_resource_id}",
                            {
                                "meta_data": [
                                    {"key": WOOCOMMERCE_VIDEO_META_KEY, "value": manifest}
                                ]
                            },
                        )
                        if res.response.status_code not in {200, 201}:
                            raise ServiceError(
                                502,
                                format_remote_http_error(
                                    action="Push product videos", result=res
                                ),
                            )
                        synced_at = utcnow()
                        for video in product_videos(db, product.id):
                            video.sync_status = "synced"
                            video.last_synced_at = synced_at
                        pushed_videos += 1
                        mark_superseded_outbox_records_synced(
                            db,
                            company_id=company_id,
                            operation=rec.operation,
                            resource_type=rec.resource_type,
                            resource_id=rec.resource_id,
                            current_record_id=rec.id,
                        )

                elif rec.resource_type == "stock":
                    mapping = db.scalar(
                        select(ExternalResourceMap).where(
                            ExternalResourceMap.company_id == company_id,
                            ExternalResourceMap.connector == CONNECTOR,
                            ExternalResourceMap.internal_resource_id == rec.resource_id,
                        )
                    )
                    if mapping:
                        variant = db.scalar(
                            select(ProductVariant).where(ProductVariant.id == rec.resource_id)
                        )
                        if variant:
                            levels = stock_levels(db, company_id=company_id, variant_id=variant.id)
                            qty = sum(level.quantity_on_hand for level in levels)
                            payload = {"manage_stock": True, "stock_quantity": qty}
                            res = make_woocommerce_request(
                                db,
                                company_id,
                                "PUT",
                                f"/products/{mapping.external_resource_id}",
                                payload,
                            )
                            if res.response.status_code not in {200, 201}:
                                raise ServiceError(
                                    502,
                                    format_remote_http_error(action="Push stock", result=res),
                                )
                            pushed += 1

                elif rec.resource_type == "order" and rec.operation == "push_status":
                    mapping = db.scalar(
                        select(ExternalResourceMap).where(
                            ExternalResourceMap.company_id == company_id,
                            ExternalResourceMap.connector == CONNECTOR,
                            ExternalResourceMap.internal_resource_type == "order",
                            ExternalResourceMap.internal_resource_id == rec.resource_id,
                        )
                    )
                    order = db.scalar(
                        select(Order).where(
                            Order.company_id == company_id,
                            Order.id == rec.resource_id,
                        )
                    )
                    if mapping and order:
                        woo_status = "pending"
                        if order.status == "pending":
                            woo_status = "pending"
                        elif order.status in {"confirmed", "packing", "ready", "dispatched"}:
                            woo_status = "processing"
                        elif order.status == "delivered":
                            woo_status = "completed"
                        elif order.status == "cancelled":
                            woo_status = "cancelled"
                        elif order.status == "refunded":
                            woo_status = "refunded"
                        res = make_woocommerce_request(
                            db,
                            company_id,
                            "PUT",
                            f"/orders/{mapping.external_resource_id}",
                            {"status": woo_status},
                        )
                        if res.response.status_code not in {200, 201}:
                            raise ServiceError(
                                502,
                                format_remote_http_error(action="Push order status", result=res),
                            )
                        pushed += 1

                rec.status = "synced"
                rec.last_error = None
                rec.next_attempt_at = None
            except WooCommerceRateLimitError:
                # The run-level scheduler owns retry timing. Do not consume an
                # outbox attempt or leave this row leased while it waits.
                rec.status = "pending"
                rec.attempts = max(0, rec.attempts - 1)
                rec.last_error = "Deferred because WooCommerce rate limited the shared sync lane."
                rec.next_attempt_at = None
                checkpoint_record()
                raise
            except Exception as exc:
                rec.status = "failed"
                rec.last_error = f"{exc} Retry scheduled when the backoff expires."
                rec.next_attempt_at = utcnow() + timedelta(minutes=5 * rec.attempts)
                failed += 1
            checkpoint_record()

    db.flush()
    return {
        "pushed": pushed,
        "pushed_media": pushed_media,
        "pushed_videos": pushed_videos,
        "failed": failed,
        "deferred": deferred,
        "deferred_videos": deferred_videos,
    }


def process_webhook_event(
    db: Session,
    company_id: str,
    topic: str | None,
    delivery_id: str | None,
    payload: dict,
) -> SyncInboxLog:
    if not delivery_id:
        raise ServiceError(422, "Webhook delivery ID header is missing.")

    existing = db.scalar(
        select(SyncInboxLog).where(
            SyncInboxLog.connector == CONNECTOR,
            SyncInboxLog.external_event_id == delivery_id,
        )
    )
    if existing:
        return existing

    inbox_log = SyncInboxLog(
        connector=CONNECTOR,
        external_event_id=delivery_id,
        event_type=topic or "unknown",
        payload=payload,
        status="received",
    )
    db.add(inbox_log)
    db.flush()

    try:
        if topic in {"product.created", "product.updated"}:
            sync_single_product(db, company_id, payload)
        elif topic in {"product.deleted", "product.trashed", "product.permanently_deleted"}:
            external_id = payload.get("id")
            if external_id is not None:
                mapping = get_external_resource_map(
                    db,
                    company_id=company_id,
                    resource_type="product",
                    external_id=str(external_id),
                )
                if mapping is not None:
                    archive_product(
                        db,
                        company_id=company_id,
                        user_id=woocommerce_sync_user_id(db, company_id),
                        product_id=mapping.internal_resource_id,
                    )
        elif topic in {"customer.created", "customer.updated"}:
            sync_single_customer(db, company_id, payload)
        elif topic in {"order.created", "order.updated"}:
            sync_single_order(db, company_id, payload)

        inbox_log.status = "processed"
        inbox_log.processed_at = utcnow()
    except Exception as exc:
        inbox_log.status = "failed"
        inbox_log.error = str(exc)

    db.flush()
    return inbox_log


def run_woocommerce_sync(
    db: Session,
    company_id: str,
    *,
    run_log: SyncRunLog | None = None,
    worker_id: str | None = None,
    commit_checkpoints: bool = False,
    progress_callback: Callable[[], None] | None = None,
    sync_mode: str | None = None,
    vendor_id: str | None = None,
) -> SyncRunLog:
    """Execute one sync run with small commits between remote-work phases.

    Normal production callers pass a claimed durable ``run_log``.  The
    optional legacy mode remains useful for service-level tests and one-off
    maintenance scripts, but the API never invokes it directly.
    """

    scoped_company_id = require_company_id(company_id)
    stored_mode = (run_log.stats or {}).get("sync_mode") if run_log is not None else None
    stored_vendor_id = (
        str((run_log.stats or {}).get("vendor_id") or "") or None
        if run_log is not None
        else None
    )
    scoped_vendor_id = vendor_id or stored_vendor_id
    if vendor_id and stored_vendor_id and vendor_id != stored_vendor_id:
        raise ServiceError(422, "Sync run does not match the requested vendor scope.")
    normalized_mode = normalize_woocommerce_sync_mode(sync_mode or stored_mode)
    if scoped_vendor_id and normalized_mode == "reconcile_products":
        raise ServiceError(403, "Vendor sync does not support product reconciliation.")
    if run_log is None:
        initial_stats = default_woocommerce_sync_stats()
        initial_stats["sync_mode"] = normalized_mode
        initial_stats["scope"] = "vendor" if scoped_vendor_id else "company"
        initial_stats["vendor_id"] = scoped_vendor_id
        run_log = SyncRunLog(
            company_id=scoped_company_id,
            connector=CONNECTOR,
            direction=(
                "outbound"
                if normalized_mode == "outbox"
                or (normalized_mode == "products" and scoped_vendor_id)
                else "both"
                if normalized_mode in {"incremental", "products"}
                else "inbound"
            ),
            status="running",
            attempts=1,
            stats=initial_stats,
        )
        db.add(run_log)
        db.flush()
    elif run_log.company_id != scoped_company_id or run_log.connector != CONNECTOR:
        raise ServiceError(422, "Sync run does not match the requested WooCommerce company.")

    run_log.status = "running"
    if worker_id:
        run_log.worker_id = worker_id
    if run_log.attempts <= 0:
        run_log.attempts = 1
    merged_stats = default_woocommerce_sync_stats()
    merged_stats.update(dict(run_log.stats or {}))
    merged_stats["sync_mode"] = normalized_mode
    merged_stats["scope"] = "vendor" if scoped_vendor_id else "company"
    merged_stats["vendor_id"] = scoped_vendor_id
    for transient_key in ("rate_limited", "retry_at", "rate_limit_reason"):
        merged_stats.pop(transient_key, None)
    run_log.stats = dict(merged_stats)

    def checkpoint() -> None:
        touch_woocommerce_sync_lease(db, run_log)
        db.flush()
        if commit_checkpoints:
            db.commit()
        if progress_callback is not None:
            progress_callback()

    try:
        stats = dict(run_log.stats or {})
        if normalized_mode == "reconcile_products":
            stats["current_phase"] = "Reconciling product IDs"
            run_log.stats = dict(stats)
            reconciliation = reconcile_products(
                db,
                scoped_company_id,
                progress_callback=checkpoint,
            )
            stats["reconciled_product_ids"] = reconciliation.get("remote_ids", 0)
            stats["archived_products"] = reconciliation.get("archived", 0)
            run_log.stats = dict(stats)
            checkpoint()
        else:
            should_push_products = normalized_mode in {"incremental", "products"}
            should_pull_taxonomies_before_push = (
                normalized_mode == "incremental" and not scoped_vendor_id
            )
            should_pull_taxonomies_after_push = (
                normalized_mode == "products" and not scoped_vendor_id
            )

            if should_pull_taxonomies_before_push:
                stats["current_phase"] = "Pulling categories and brands"
                run_log.stats = dict(stats)
                stats_taxonomies = pull_categories(
                    db,
                    scoped_company_id,
                    progress_callback=checkpoint,
                )
                stats["pulled_categories"] = stats_taxonomies.get("pulled", 0)
                stats_brands = pull_brands(
                    db,
                    scoped_company_id,
                    progress_callback=checkpoint,
                )
                stats["pulled_brands"] = stats_brands.get("pulled", 0)
                run_log.stats = dict(stats)
                checkpoint()

            if should_push_products or normalized_mode == "outbox":
                stats["current_phase"] = "Syncing brands and categories"
                run_log.stats = dict(stats)
                outbox_product_ids = (
                    pending_product_outbox_ids(db, scoped_company_id)
                    if normalized_mode == "outbox"
                    else None
                )
                taxonomy_stats = sync_local_taxonomies_for_sync(
                    db,
                    scoped_company_id,
                    vendor_id=scoped_vendor_id,
                    product_ids=outbox_product_ids,
                )
                stats["synced_categories"] = taxonomy_stats["synced_categories"]
                stats["synced_brands"] = taxonomy_stats["synced_brands"]
                stats["failed_taxonomies"] = taxonomy_stats["failed_taxonomies"]
                stats["taxonomy_errors"] = taxonomy_stats["taxonomy_errors"]
                run_log.stats = dict(stats)
                checkpoint()
                taxonomy_errors = taxonomy_stats["taxonomy_errors"]
                if taxonomy_errors:
                    raise ServiceError(
                        502,
                        "WooCommerce taxonomy sync failed: "
                        + "; ".join(str(error) for error in taxonomy_errors),
                    )

                if not should_push_products:
                    stats["current_phase"] = "Syncing queued products"
                    run_log.stats = dict(stats)
                    stats_push = process_sync_outbox(
                        db,
                        scoped_company_id,
                        checkpoint=checkpoint if commit_checkpoints else None,
                    )
                    stats["pushed_records"] = stats_push.get("pushed", 0)
                    stats["pushed_media_records"] = stats_push.get("pushed_media", 0)
                    stats["pushed_video_records"] = stats_push.get("pushed_videos", 0)
                    stats["failed_records"] = stats_push.get("failed", 0)
                    run_log.stats = dict(stats)
                    checkpoint()

            if should_push_products:
                stats["current_phase"] = "Preparing product queue"
                video_outbox_ids_before = set(
                    db.scalars(
                        select(SyncOutbox.id).where(
                            SyncOutbox.company_id == scoped_company_id,
                            SyncOutbox.connector == CONNECTOR,
                            SyncOutbox.resource_type == "product",
                            SyncOutbox.operation == "push_videos",
                        )
                    ).all()
                )
                queued_products = enqueue_products_for_sync(
                    db,
                    scoped_company_id,
                    vendor_id=scoped_vendor_id,
                )
                queued_media = enqueue_pending_product_media_for_sync(
                    db,
                    scoped_company_id,
                    vendor_id=scoped_vendor_id,
                )
                video_outbox_ids_after = set(
                    db.scalars(
                        select(SyncOutbox.id).where(
                            SyncOutbox.company_id == scoped_company_id,
                            SyncOutbox.connector == CONNECTOR,
                            SyncOutbox.resource_type == "product",
                            SyncOutbox.operation == "push_videos",
                        )
                    ).all()
                )
                stats["queued_product_pushes"] = queued_products
                stats["queued_media_pushes"] = queued_media
                stats["queued_video_pushes"] = len(
                    video_outbox_ids_after - video_outbox_ids_before
                )
                run_log.stats = dict(stats)
                checkpoint()

                stats["current_phase"] = "Syncing queued products"
                run_log.stats = dict(stats)
                stats_push = process_sync_outbox(
                    db,
                    scoped_company_id,
                    vendor_id=scoped_vendor_id,
                    checkpoint=checkpoint if commit_checkpoints else None,
                )
                stats["pushed_records"] = stats_push.get("pushed", 0)
                stats["pushed_media_records"] = stats_push.get("pushed_media", 0)
                stats["pushed_video_records"] = stats_push.get("pushed_videos", 0)
                stats["failed_records"] = stats_push.get("failed", 0)
                stats["deferred_media_records"] = stats_push.get("deferred", 0)
                stats["deferred_video_records"] = stats_push.get("deferred_videos", 0)
                run_log.stats = dict(stats)
                checkpoint()

            if should_pull_taxonomies_after_push:
                stats["current_phase"] = "Pulling categories and brands"
                run_log.stats = dict(stats)
                stats_taxonomies = pull_categories(
                    db,
                    scoped_company_id,
                    progress_callback=checkpoint,
                )
                stats["pulled_categories"] = stats_taxonomies.get("pulled", 0)
                stats_brands = pull_brands(
                    db,
                    scoped_company_id,
                    progress_callback=checkpoint,
                )
                stats["pulled_brands"] = stats_brands.get("pulled", 0)
                run_log.stats = dict(stats)
                checkpoint()

            should_pull_products = normalized_mode in {"incremental", "products", "full_products"}
            if should_pull_products and not (normalized_mode == "products" and scoped_vendor_id):
                stats["current_phase"] = "Pulling products"
                run_log.stats = dict(stats)
                stats_prod = pull_products(
                    db,
                    scoped_company_id,
                    progress_callback=checkpoint,
                    force_full=bool(scoped_vendor_id)
                    or normalized_mode in {"full_products", "products"},
                    vendor_id=scoped_vendor_id,
                )
                stats["pulled_products"] = stats_prod.get("pulled", 0)
                run_log.stats = dict(stats)
                checkpoint()

            if normalized_mode == "incremental" and not scoped_vendor_id:
                stats["current_phase"] = "Pulling customers"
                run_log.stats = dict(stats)
                stats_cust = pull_customers(
                    db,
                    scoped_company_id,
                    progress_callback=checkpoint,
                )
                stats["pulled_customers"] = stats_cust.get("pulled", 0)
                run_log.stats = dict(stats)
                checkpoint()

                stats["current_phase"] = "Pulling orders"
                run_log.stats = dict(stats)
                stats_ord = pull_orders(
                    db,
                    scoped_company_id,
                    progress_callback=checkpoint,
                )
                stats["pulled_orders"] = stats_ord.get("pulled", 0)

        stats["current_phase"] = "Finalizing sync"
        run_log.stats = dict(stats)
        if normalized_mode in {"incremental", "products", "full_products", "outbox"}:
            stats.update(
                woocommerce_sync_outbox_status(
                    db, scoped_company_id, vendor_id=scoped_vendor_id
                )
            )
        run_log.stats = dict(stats)
        pending_outbound = int(stats.get("pending_product_pushes", 0)) + int(
            stats.get("pending_media_pushes", 0)
        ) + int(stats.get("pending_video_pushes", 0))
        failed_outbound = int(stats.get("failed_product_pushes", 0)) + int(
            stats.get("failed_media_pushes", 0)
        ) + int(stats.get("failed_video_pushes", 0)) + int(
            stats.get("failed_taxonomies", 0)
        )
        if pending_outbound or failed_outbound:
            run_log.status = "failed"
            run_log.error = (
                "Sync finished with unresolved outbound work: "
                f"{failed_outbound} failed and {pending_outbound} pending record(s)."
            )
        else:
            run_log.status = "success"
            run_log.error = None
        run_log.finished_at = utcnow()
        run_log.lease_expires_at = None
        run_log.next_attempt_at = None
        run_log.active_key = None
    except WooCommerceRateLimitError as exc:
        # Keep the same active key and replay the durable run later. Existing
        # mappings/outbox rows make repeating a partially completed run safe.
        if run_log.attempts >= RATE_LIMIT_MAX_RUN_ATTEMPTS:
            run_log.status = "failed"
            run_log.error = (
                f"WooCommerce remained rate limited after {run_log.attempts} attempts: {exc}"
            )
            run_log.finished_at = utcnow()
            run_log.active_key = None
            run_log.next_attempt_at = None
        else:
            exponential_delay = min(
                RATE_LIMIT_DEFAULT_DELAY_SECONDS * (2 ** max(run_log.attempts - 1, 0)),
                RATE_LIMIT_MAX_DELAY_SECONDS,
            )
            delay = min(
                max(exc.retry_after_seconds, exponential_delay), RATE_LIMIT_MAX_DELAY_SECONDS
            )
            delay *= random.uniform(0.9, 1.1)
            retry_at = utcnow() + timedelta(seconds=delay)
            stats = dict(run_log.stats or {})
            stats.update(
                {
                    "current_phase": "Rate limited; retrying automatically",
                    "rate_limited": True,
                    "retry_at": retry_at.isoformat(),
                    "rate_limit_reason": str(exc),
                }
            )
            run_log.stats = stats
            run_log.status = "queued"
            run_log.error = f"WooCommerce rate limited; retrying at {retry_at.isoformat()}."
            run_log.finished_at = None
            run_log.lease_expires_at = None
            run_log.next_attempt_at = retry_at
            run_log.worker_id = None
    except Exception as exc:
        # A database error aborts the transaction. Roll it back before marking
        # the durable run as failed, otherwise the lease remains stuck running.
        run_log_id = run_log.id
        db.rollback()
        run_log = db.get(SyncRunLog, run_log_id)
        if run_log is None:
            raise
        run_log.status = "failed"
        run_log.error = str(exc)
        run_log.finished_at = utcnow()
        run_log.lease_expires_at = None
        run_log.next_attempt_at = None
        run_log.active_key = None

    db.flush()
    if commit_checkpoints:
        db.commit()
    return run_log


def execute_woocommerce_sync_run(
    db: Session,
    *,
    run_log_id: str,
    worker_id: str,
    progress_callback: Callable[[], None] | None = None,
) -> SyncRunLog | None:
    """Run an already-claimed durable job, preserving its audit identity."""

    run_log = db.scalar(
        select(SyncRunLog).where(
            SyncRunLog.id == run_log_id,
            SyncRunLog.connector == CONNECTOR,
        )
    )
    if run_log is None:
        return None
    if run_log.status != "running":
        return run_log
    if not run_log.company_id:
        run_log.status = "failed"
        run_log.error = "Claimed sync job has no company scope."
        run_log.finished_at = utcnow()
        run_log.active_key = None
        run_log.lease_expires_at = None
        db.commit()
        return run_log
    return run_woocommerce_sync(
        db,
        run_log.company_id,
        run_log=run_log,
        worker_id=worker_id,
        commit_checkpoints=True,
        progress_callback=progress_callback,
    )


def resolve_sync_conflict(
    db: Session,
    company_id: str,
    conflict_id: str,
    payload: SyncConflictResolveRequest,
    *,
    user_id: str,
) -> SyncConflict:
    conflict = db.scalar(
        select(SyncConflict).where(
            SyncConflict.company_id == company_id,
            SyncConflict.id == conflict_id,
        )
    )
    if conflict is None:
        raise ServiceError(404, "Conflict not found.")

    conflict.status = "resolved"
    conflict.resolution = payload.resolution

    if payload.strategy == "use_local":
        if conflict.resource_type == "product" and conflict.resource_id:
            enqueue_sync_outbox(
                db,
                company_id=company_id,
                operation="push",
                resource_type="product",
                resource_id=conflict.resource_id,
                payload=conflict.local_payload,
            )
    elif payload.strategy == "use_remote":
        if conflict.resource_type == "product" and conflict.resource_id:
            product = db.scalar(select(Product).where(Product.id == conflict.resource_id))
            if product:
                product.name = conflict.remote_payload.get("name", product.name)
                db.flush()

    db.flush()
    record_audit(
        db,
        action="woocommerce.conflict_resolved",
        company_id=company_id,
        user_id=user_id,
        entity_type="conflict",
        entity_id=conflict_id,
        metadata={"strategy": payload.strategy},
    )
    return conflict


def list_sync_runs(
    db: Session, company_id: str, *, vendor_id: str | None = None
) -> list[SyncRunLog]:
    runs = list(
        db.scalars(
            select(SyncRunLog)
            .where(
                SyncRunLog.company_id == company_id,
                SyncRunLog.connector == CONNECTOR,
            )
            .order_by(SyncRunLog.started_at.desc())
        ).all()
    )
    if vendor_id:
        runs = [
            run
            for run in runs
            if str((run.stats or {}).get("vendor_id") or "") == vendor_id
        ]
    return runs


def list_sync_conflicts(db: Session, company_id: str) -> list[SyncConflict]:
    return list(
        db.scalars(
            select(SyncConflict)
            .where(
                SyncConflict.company_id == company_id,
                SyncConflict.connector == CONNECTOR,
            )
            .order_by(SyncConflict.created_at.desc())
        ).all()
    )
