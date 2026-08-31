from __future__ import annotations

import logging
import re
import time
import uuid
from collections import deque
from http import HTTPStatus
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.httpsredirect import HTTPSRedirectMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.staticfiles import StaticFiles
from starlette.datastructures import Headers
from starlette.responses import JSONResponse
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

from erp import __version__
from erp.apps.api.web import AUTH_WEB_PATHS, apply_auth_security_headers
from erp.apps.api.web import router as web_router
from erp.packages.core.api.accounting_routes import router as accounting_router
from erp.packages.core.api.commerce_routes import router as commerce_router
from erp.packages.core.api.delivery_routes import router as delivery_router
from erp.packages.core.api.finance_routes import router as finance_router
from erp.packages.core.api.ledger_routes import router as ledger_router
from erp.packages.core.api.marketplace_routes import router as marketplace_router
from erp.packages.core.api.push_routes import router as push_router
from erp.packages.core.api.routes import router as core_router
from erp.packages.core.config import Settings, get_settings
from erp.packages.core.logging import (
    configure_logging,
    current_request_id,
    reset_request_id,
    set_request_id,
)

LOGGER = logging.getLogger(__name__)
REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9._-]{8,128}$")


def request_operation(request: Request) -> str:
    return f"{request.method} {request.url.path}"


def safe_request_id(request: Request) -> str:
    return _safe_request_id(request.headers.get("X-Request-ID", ""))


def _safe_request_id(supplied: str) -> str:
    supplied = supplied.strip()
    if REQUEST_ID_PATTERN.fullmatch(supplied):
        return supplied
    return uuid.uuid4().hex


class RequestSizeLimitMiddleware:
    """Reject request bodies larger than the configured bounded in-memory limit."""

    def __init__(self, app, max_body_size: int) -> None:  # type: ignore[no-untyped-def]
        self.app = app
        self.max_body_size = max_body_size

    async def __call__(self, scope, receive, send) -> None:  # type: ignore[no-untyped-def]
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = Headers(scope=scope)
        content_length = headers.get("content-length")
        if content_length is not None:
            try:
                if int(content_length) > self.max_body_size:
                    await self._send_payload_too_large(scope, receive, send)
                    return
            except ValueError:
                pass

        buffered_messages = deque()
        received_size = 0
        more_body = True
        while more_body:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            if message["type"] != "http.request":
                continue
            received_size += len(message.get("body", b""))
            if received_size > self.max_body_size:
                await self._send_payload_too_large(scope, receive, send)
                return
            buffered_messages.append(message)
            more_body = message.get("more_body", False)

        async def replay_receive() -> dict[str, object]:
            if buffered_messages:
                return buffered_messages.popleft()
            return {"type": "http.disconnect"}

        await self.app(scope, replay_receive, send)

    @staticmethod
    async def _send_payload_too_large(scope, receive, send) -> None:  # type: ignore[no-untyped-def]
        request_id = scope.get("state", {}).get("request_id")
        if not isinstance(request_id, str):
            request_id = _safe_request_id(Headers(scope=scope).get("X-Request-ID", ""))
        response = JSONResponse(
            status_code=413,
            content={
                "detail": "Request body exceeds the configured maximum size.",
                "request_id": request_id,
                "operation": f"{scope['method']} {scope['path']}",
            },
            headers={"X-Request-ID": request_id},
        )
        await response(scope, receive, send)


def create_app(settings_override: Settings | None = None) -> FastAPI:
    settings = settings_override or get_settings()
    configure_logging(
        settings.log_level,
        log_dir=settings.log_dir,
        max_bytes=settings.log_max_bytes,
        backup_count=settings.log_backup_count,
    )
    app = FastAPI(
        title=settings.app_name,
        version=__version__,
        docs_url="/docs" if settings.effective_docs_enabled else None,
        redoc_url="/redoc" if settings.effective_docs_enabled else None,
        openapi_url="/openapi.json" if settings.effective_docs_enabled else None,
    )
    app.state.settings = settings
    # HTTPS is normally terminated by a loopback reverse proxy. Apply its
    # trusted forwarding headers before redirecting, never for public clients.
    if settings.force_https:
        app.add_middleware(HTTPSRedirectMiddleware)
    if settings.trusted_proxy_ips:
        app.add_middleware(
            ProxyHeadersMiddleware,
            trusted_hosts=settings.trusted_proxy_ips,
        )
    if settings.trusted_hosts and settings.trusted_hosts != ["*"]:
        app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.trusted_hosts)
    if settings.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origins,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )
    app.add_middleware(
        RequestSizeLimitMiddleware,
        max_body_size=settings.max_request_size_mb * 1024 * 1024,
    )

    @app.exception_handler(HTTPException)
    async def safe_http_exception(request: Request, exc: HTTPException) -> JSONResponse:
        request_id = current_request_id() or getattr(request.state, "request_id", "unknown")
        operation = request_operation(request)
        if exc.status_code >= 500:
            LOGGER.error(
                "API HTTP exception",
                extra={
                    "operation": operation,
                    "method": request.method,
                    "path": request.url.path,
                    "status_code": exc.status_code,
                },
            )
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "detail": exc.detail,
                "request_id": request_id,
                "operation": operation,
            },
            headers={**(exc.headers or {}), "X-Request-ID": request_id},
        )

    @app.exception_handler(RequestValidationError)
    async def safe_validation_exception(
        request: Request,
        exc: RequestValidationError,
    ) -> JSONResponse:
        request_id = current_request_id() or getattr(request.state, "request_id", "unknown")
        errors = [
            {"loc": list(error.get("loc", ())), "msg": error.get("msg"), "type": error.get("type")}
            for error in exc.errors()
        ]
        return JSONResponse(
            status_code=422,
            content={
                "detail": "Request validation failed.",
                "errors": errors,
                "request_id": request_id,
                "operation": request_operation(request),
            },
            headers={"X-Request-ID": request_id},
        )

    @app.middleware("http")
    async def production_feature_gate(request, call_next):  # type: ignore[no-untyped-def]
        app_settings: Settings = request.app.state.settings
        whatsapp_prefix = f"{app_settings.api_prefix.rstrip('/')}/whatsapp"
        if (
            request.url.path.startswith(whatsapp_prefix)
            and not app_settings.effective_whatsapp_enabled
        ):
            request_id = current_request_id() or getattr(request.state, "request_id", None)
            request_id = request_id or safe_request_id(request)
            return JSONResponse(
                {
                    "detail": "WhatsApp module is disabled.",
                    "request_id": request_id,
                    "operation": request_operation(request),
                },
                status_code=404,
                headers={"X-Request-ID": request_id},
            )
        return await call_next(request)

    @app.middleware("http")
    async def request_context_and_errors(request: Request, call_next):  # type: ignore[no-untyped-def]
        request_id = safe_request_id(request)
        request.state.request_id = request_id
        context_token = set_request_id(request_id)
        started = time.perf_counter()
        operation = request_operation(request)
        try:
            try:
                response = await call_next(request)
            except Exception:
                LOGGER.exception(
                    "Unhandled API exception",
                    extra={
                        "operation": operation,
                        "method": request.method,
                        "path": request.url.path,
                        "status_code": 500,
                    },
                )
                response = JSONResponse(
                    status_code=500,
                    content={
                        "detail": "Internal Server Error",
                        "request_id": request_id,
                        "operation": operation,
                    },
                )
            # Starlette's router and security middleware can return a response
            # directly (for example 404, 405, or an invalid Host) without passing
            # through FastAPI's HTTPException handler. Normalize those safe errors
            # so desktop/API callers always receive the request ID and operation.
            is_html_response = response.headers.get("content-type", "").startswith("text/html")
            if (
                response.status_code >= 400
                and "X-Request-ID" not in response.headers
                and not is_html_response
            ):
                forwarded_headers = {
                    key: value
                    for key, value in response.headers.items()
                    if key.lower() not in {"content-length", "content-type", "x-request-id"}
                }
                try:
                    detail = HTTPStatus(response.status_code).phrase
                except ValueError:  # pragma: no cover - non-standard proxy status
                    detail = "Request failed"
                response = JSONResponse(
                    status_code=response.status_code,
                    content={
                        "detail": detail,
                        "request_id": request_id,
                        "operation": operation,
                    },
                    headers=forwarded_headers,
                )
        finally:
            elapsed_ms = round((time.perf_counter() - started) * 1000, 1)
            reset_request_id(context_token)
        response.headers["X-Request-ID"] = request_id
        LOGGER.info(
            "API request completed",
            extra={
                "request_id": request_id,
                "operation": operation,
                "method": request.method,
                "path": request.url.path,
                "status_code": response.status_code,
                "elapsed_ms": elapsed_ms,
            },
        )
        return response

    @app.middleware("http")
    async def secure_auth_web_responses(request: Request, call_next):  # type: ignore[no-untyped-def]
        response = await call_next(request)
        if request.url.path in AUTH_WEB_PATHS:
            apply_auth_security_headers(response)
        return response

    app.include_router(core_router, prefix=settings.api_prefix)
    app.include_router(marketplace_router, prefix=settings.api_prefix)
    app.include_router(accounting_router, prefix=settings.api_prefix)
    app.include_router(commerce_router, prefix=settings.api_prefix)
    app.include_router(delivery_router, prefix=settings.api_prefix)
    app.include_router(finance_router, prefix=settings.api_prefix)
    app.include_router(ledger_router, prefix=settings.api_prefix)
    app.include_router(push_router, prefix=settings.api_prefix)
    app.include_router(web_router)
    web_assets_dir = Path(__file__).with_name("static")
    app.mount("/web-assets", StaticFiles(directory=str(web_assets_dir)), name="web-assets")
    media_dir = Path(settings.media_upload_dir)
    media_dir.mkdir(parents=True, exist_ok=True)
    app.mount("/media", StaticFiles(directory=str(media_dir)), name="media")
    return app


app = create_app()
