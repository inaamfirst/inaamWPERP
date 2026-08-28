from __future__ import annotations

# HTML form markup remains readable as complete tags.
# ruff: noqa: E501
import hashlib
import hmac
from collections.abc import Callable
from html import escape
from typing import Annotated
from urllib.parse import quote, urlsplit

from fastapi import APIRouter, Depends, Form, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from erp.packages.core.auth_delivery import deliver_action_token
from erp.packages.core.config import Settings, get_settings
from erp.packages.core.db.models import Company, Product, Vendor
from erp.packages.core.db.session import get_session
from erp.packages.core.schemas import VendorRegistrationRequest
from erp.packages.core.security import generate_session_token, hash_session_token
from erp.packages.core.services import (
    IssuedSession,
    ServiceError,
    auth_throttle_scope_keys,
    authenticate,
    check_auth_throttle,
    confirm_activation,
    confirm_password_reset,
    context_from_token,
    create_action_token,
    normalize_company_slug,
    record_auth_throttle_attempt,
    revoke_refresh_token,
    revoke_session,
    rotate_refresh_token,
)
from erp.packages.core.vendor_auth_services import (
    find_password_reset_user,
    register_public_vendor,
)

router = APIRouter()
DbSession = Annotated[Session, Depends(get_session)]

ACCESS_COOKIE = "erp_access"
REFRESH_COOKIE = "erp_refresh"
CSRF_COOKIE = "erp_csrf"
ACTIVATION_COOKIE = "erp_activation_action"
RESET_COOKIE = "erp_reset_action"
CSRF_MAX_AGE_SECONDS = 30 * 60
AUTH_WEB_PATHS = frozenset(
    {
        "/login",
        "/register",
        "/register/success",
        "/forgot-password",
        "/reset-password",
        "/activate",
        "/account",
        "/session/refresh",
        "/logout",
    }
)
AUTH_CSP = (
    "default-src 'none'; style-src 'self'; img-src 'self' data:; "
    "form-action 'self'; base-uri 'none'; frame-ancestors 'none'"
)


def apply_auth_security_headers(response: Response) -> Response:
    response.headers["Cache-Control"] = "no-store, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Content-Security-Policy"] = AUTH_CSP
    return response


def request_settings(request: Request) -> Settings:
    return getattr(request.app.state, "settings", get_settings())


def cookie_secure(settings: Settings) -> bool:
    return settings.is_production or settings.force_https


def client_ip(request: Request) -> str | None:
    # ProxyHeadersMiddleware rewrites request.client only for configured trusted
    # proxy peers. Never inspect forwarding headers directly here.
    return request.client.host if request.client else None


def safe_next_url(candidate: str | None, *, default: str = "/account") -> str:
    value = (candidate or "").strip()
    if not value or len(value) > 2048 or any(ord(char) < 32 for char in value):
        return default
    parsed = urlsplit(value)
    if (
        parsed.scheme
        or parsed.netloc
        or not parsed.path.startswith("/")
        or parsed.path.startswith("//")
        or "\\" in value
    ):
        return default
    return value


def _csrf_binding(purpose: str, binding_token: str | None) -> str:
    token_digest = (
        hashlib.sha256(binding_token.encode("utf-8")).hexdigest() if binding_token else "anonymous"
    )
    return f"{purpose}:{token_digest}"


def _csrf_signature(settings: Settings, nonce: str, binding: str) -> str:
    message = f"erp-web-csrf-v1|{binding}|{nonce}".encode()
    return hmac.new(settings.secret_key.encode(), message, hashlib.sha256).hexdigest()


def issue_csrf_token(
    settings: Settings,
    *,
    purpose: str,
    binding_token: str | None = None,
) -> str:
    nonce = generate_session_token()
    binding = _csrf_binding(purpose, binding_token)
    return f"{nonce}.{_csrf_signature(settings, nonce, binding)}"


def set_csrf_cookie(response: Response, token: str, settings: Settings) -> None:
    response.set_cookie(
        CSRF_COOKIE,
        token,
        max_age=CSRF_MAX_AGE_SECONDS,
        path="/",
        httponly=True,
        secure=cookie_secure(settings),
        samesite="strict",
    )


def new_csrf_response(
    request: Request,
    title: str,
    body_factory: Callable[[str], str],
    *,
    purpose: str,
    binding_token: str | None = None,
    status_code: int = 200,
) -> HTMLResponse:
    settings = request_settings(request)
    token = issue_csrf_token(
        settings,
        purpose=purpose,
        binding_token=binding_token,
    )
    response = page(title, body_factory(token), status_code=status_code)
    set_csrf_cookie(response, token, settings)
    return response


def verify_csrf(
    request: Request,
    supplied: str,
    *,
    purpose: str,
    binding_tokens: tuple[str | None, ...] = (None,),
) -> None:
    cookie = request.cookies.get(CSRF_COOKIE, "")
    if not cookie or not supplied or not hmac.compare_digest(cookie, supplied):
        raise HTTPException(status_code=403, detail="Invalid form submission.")
    try:
        nonce, signature = supplied.rsplit(".", 1)
    except ValueError as exc:
        raise HTTPException(status_code=403, detail="Invalid form submission.") from exc
    settings = request_settings(request)
    valid_signature = False
    for binding_token in binding_tokens:
        binding = _csrf_binding(purpose, binding_token)
        expected = _csrf_signature(settings, nonce, binding)
        valid_signature = hmac.compare_digest(signature, expected) or valid_signature
    if not valid_signature:
        raise HTTPException(status_code=403, detail="Invalid form submission.")


def _persistent_cookie_max_age(expires_at) -> int:  # type: ignore[no-untyped-def]
    from erp.packages.core.services import to_utc, utcnow

    expires = to_utc(expires_at)
    return max(1, int((expires - utcnow()).total_seconds())) if expires else 1


def set_session_cookies(
    response: Response,
    issued: IssuedSession,
    settings: Settings,
) -> None:
    common = {
        "path": "/",
        "httponly": True,
        "secure": cookie_secure(settings),
    }
    access_options = {**common, "samesite": "lax"}
    refresh_options = {**common, "samesite": "strict"}
    if issued.remember_me:
        access_options["max_age"] = _persistent_cookie_max_age(issued.session.expires_at)
        refresh_options["max_age"] = _persistent_cookie_max_age(issued.refresh_expires_at)
    response.set_cookie(ACCESS_COOKIE, issued.token, **access_options)
    if issued.refresh_token:
        response.set_cookie(REFRESH_COOKIE, issued.refresh_token, **refresh_options)


def _delete_cookie(
    response: Response,
    name: str,
    settings: Settings,
    *,
    path: str,
    samesite: str,
) -> None:
    response.delete_cookie(
        name,
        path=path,
        httponly=True,
        secure=cookie_secure(settings),
        samesite=samesite,
    )


def clear_auth_cookies(response: Response, settings: Settings) -> None:
    _delete_cookie(response, ACCESS_COOKIE, settings, path="/", samesite="lax")
    _delete_cookie(response, REFRESH_COOKIE, settings, path="/", samesite="strict")
    _delete_cookie(response, CSRF_COOKIE, settings, path="/", samesite="strict")
    _delete_cookie(
        response,
        ACTIVATION_COOKIE,
        settings,
        path="/activate",
        samesite="strict",
    )
    _delete_cookie(
        response,
        RESET_COOKIE,
        settings,
        path="/reset-password",
        samesite="strict",
    )


def set_action_cookie(
    response: Response,
    *,
    name: str,
    token: str,
    path: str,
    settings: Settings,
) -> None:
    response.set_cookie(
        name,
        token,
        max_age=settings.action_token_ttl_minutes * 60,
        path=path,
        httponly=True,
        secure=cookie_secure(settings),
        samesite="strict",
    )


def clear_action_cookie(
    response: Response,
    *,
    name: str,
    path: str,
    settings: Settings,
) -> None:
    _delete_cookie(response, name, settings, path=path, samesite="strict")


def page(title: str, body: str, *, status_code: int = 200) -> HTMLResponse:
    return HTMLResponse(
        f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="color-scheme" content="light">
  <title>{escape(title)}</title>
  <link rel="stylesheet" href="/web-assets/web.css">
</head>
<body>{body}</body>
</html>""",
        status_code=status_code,
    )


def auth_form(
    title: str,
    action: str,
    csrf: str,
    workspace: str = "",
    error: str = "",
    next_url: str = "/account",
) -> str:
    error_html = f'<p class="error" role="alert">{escape(error)}</p>' if error else ""
    workspace_query = quote(workspace, safe="")
    return f"""<header><h1>{escape(title)}</h1></header><main>
{error_html}<form method="post" action="{escape(action)}">
<input type="hidden" name="csrf_token" value="{escape(csrf)}">
<input type="hidden" name="next" value="{escape(next_url)}">
<label>Workspace <input name="workspace_slug" value="{escape(workspace)}" required></label>
<label>Login ID or email <input name="username" autocomplete="username" required></label>
<label>Password <input type="password" name="password" autocomplete="current-password" required></label>
<label class="inline"><input type="checkbox" name="remember_me" value="yes"> Remember me securely</label>
<button type="submit">Sign in</button></form>
<p><a href="/forgot-password?workspace={workspace_query}">Forgot password?</a></p>
<p><a href="/register?workspace={workspace_query}">Register as a vendor</a></p></main>"""


@router.get("/", include_in_schema=False)
def root() -> RedirectResponse:
    return RedirectResponse("/marketplace", status_code=307)


@router.get("/marketplace", response_class=HTMLResponse, include_in_schema=False)
def marketplace_landing() -> HTMLResponse:
    return page(
        "Marketplace",
        """<header><h1>Enterprise Commerce ERP Marketplace</h1></header>
<main>
  <p class="muted">Open a storefront at <code>/store/&lt;workspace-slug&gt;</code>.</p>
</main>""",
    )


@router.get("/login", response_class=HTMLResponse, include_in_schema=False)
def login_page(request: Request, workspace: str = "", next: str = "/account") -> HTMLResponse:
    next_url = safe_next_url(next)
    return new_csrf_response(
        request,
        "Sign in",
        lambda csrf: auth_form("Sign in", "/login", csrf, workspace, next_url=next_url),
        purpose="login",
    )


@router.post("/login", response_class=HTMLResponse, include_in_schema=False)
def login_submit(
    request: Request,
    db: DbSession,
    csrf_token: Annotated[str, Form(max_length=256)] = "",
    workspace_slug: Annotated[str, Form(min_length=2, max_length=120)] = "",
    username: Annotated[str, Form(min_length=1, max_length=255)] = "",
    password: Annotated[str, Form(min_length=1, max_length=128)] = "",
    remember_me: Annotated[str | None, Form()] = None,
    next: Annotated[str, Form(max_length=2048)] = "/account",
) -> HTMLResponse:
    verify_csrf(request, csrf_token, purpose="login")
    settings = request_settings(request)
    next_url = safe_next_url(next)
    try:
        issued = authenticate(
            db,
            username=username,
            password=password,
            workspace_slug=workspace_slug,
            user_agent=request.headers.get("user-agent"),
            ip_address=client_ip(request),
            remember_me=remember_me == "yes",
            refresh_capable=True,
        )
        db.commit()
    except ServiceError as exc:
        if exc.status_code in {401, 403, 409, 429}:
            db.commit()
        else:
            db.rollback()
        status_code = exc.status_code if exc.status_code in {401, 403, 429} else 401
        message = (
            "Too many sign-in attempts. Please try again later."
            if status_code == 429
            else "Unable to sign in with those credentials."
        )
        return new_csrf_response(
            request,
            "Sign in",
            lambda csrf: auth_form(
                "Sign in",
                "/login",
                csrf,
                workspace_slug,
                message,
                next_url,
            ),
            purpose="login",
            status_code=status_code,
        )
    response = RedirectResponse(next_url, status_code=303)
    set_session_cookies(response, issued, settings)
    _delete_cookie(response, CSRF_COOKIE, settings, path="/", samesite="strict")
    return response


def registration_form(csrf: str, workspace: str, error: str = "") -> str:
    error_html = f'<p class="error" role="alert">{escape(error)}</p>' if error else ""
    workspace_query = quote(workspace, safe="")
    return f"""<header><h1>Vendor registration</h1></header><main>{error_html}
<form method="post" action="/register">
<input type="hidden" name="csrf_token" value="{escape(csrf)}">
<label>Workspace <input name="workspace_slug" value="{escape(workspace)}" required></label>
<label>Business name <input name="business_name" required></label>
<label>Contact name <input name="contact_name"></label>
<label>Email <input type="email" name="email" autocomplete="email" required></label>
<label>Phone <input name="phone"></label>
<label>Login ID <input name="username" autocomplete="username" required></label>
<label>Password <input type="password" name="password" minlength="8" autocomplete="new-password" required></label>
<button type="submit">Submit registration</button></form>
<p class="muted">New vendor accounts remain pending until an administrator approves them.</p>
<p><a href="/login?workspace={workspace_query}">Back to sign in</a></p></main>"""


@router.get("/register", response_class=HTMLResponse, include_in_schema=False)
def register_page(request: Request, workspace: str = "") -> HTMLResponse:
    return new_csrf_response(
        request,
        "Vendor registration",
        lambda csrf: registration_form(csrf, workspace),
        purpose="register",
    )


@router.post("/register", response_class=HTMLResponse, include_in_schema=False)
def register_submit(
    request: Request,
    db: DbSession,
    csrf_token: Annotated[str, Form(max_length=256)] = "",
    workspace_slug: Annotated[str, Form(min_length=2, max_length=120)] = "",
    business_name: Annotated[str, Form(min_length=2, max_length=255)] = "",
    username: Annotated[str, Form(min_length=3, max_length=120)] = "",
    email: Annotated[str, Form(min_length=3, max_length=255)] = "",
    password: Annotated[str, Form(min_length=8, max_length=128)] = "",
    contact_name: Annotated[str | None, Form(max_length=255)] = None,
    phone: Annotated[str | None, Form(max_length=80)] = None,
) -> Response:
    verify_csrf(request, csrf_token, purpose="register")
    scope_keys = auth_throttle_scope_keys(
        action="vendor_registration",
        account_identifier=username,
        workspace=workspace_slug,
        ip_address=client_ip(request),
    )
    try:
        check_auth_throttle(db, scope_keys)
        register_public_vendor(
            db,
            VendorRegistrationRequest(
                workspace_slug=workspace_slug,
                business_name=business_name,
                username=username,
                email=email,
                password=password,
                contact_name=contact_name or None,
                phone=phone or None,
            ),
        )
        record_auth_throttle_attempt(db, scope_keys)
        db.commit()
    except ServiceError as exc:
        db.rollback()
        if exc.status_code != 429:
            record_auth_throttle_attempt(db, scope_keys)
            db.commit()
        message = (
            "Too many registration attempts. Please try again later."
            if exc.status_code == 429
            else "Registration could not be completed. Please check the form and try again."
        )
        return new_csrf_response(
            request,
            "Vendor registration",
            lambda csrf: registration_form(csrf, workspace_slug, message),
            purpose="register",
            status_code=429 if exc.status_code == 429 else 400,
        )
    except (IntegrityError, ValueError):
        db.rollback()
        record_auth_throttle_attempt(db, scope_keys)
        db.commit()
        return new_csrf_response(
            request,
            "Vendor registration",
            lambda csrf: registration_form(
                csrf,
                workspace_slug,
                "Registration could not be completed. Please check the form and try again.",
            ),
            purpose="register",
            status_code=400,
        )
    settings = request_settings(request)
    response = RedirectResponse("/register/success", status_code=303)
    _delete_cookie(response, CSRF_COOKIE, settings, path="/", samesite="strict")
    return response


@router.get("/register/success", response_class=HTMLResponse, include_in_schema=False)
def registration_success_page() -> HTMLResponse:
    return page(
        "Registration received",
        """<header><h1>Registration received</h1></header><main>
<p>Your vendor account is pending administrator approval. You cannot access vendor records yet.</p>
<p><a href="/login">Return to sign in</a></p></main>""",
    )


@router.get("/account", response_class=HTMLResponse, include_in_schema=False)
def account_page(request: Request, db: DbSession) -> Response:
    access_token = request.cookies.get(ACCESS_COOKIE)
    if access_token:
        try:
            context = context_from_token(db, access_token)
        except ServiceError:
            context = None
    else:
        context = None
    if context is None:
        refresh_token = request.cookies.get(REFRESH_COOKIE)
        if refresh_token:
            return new_csrf_response(
                request,
                "Continue session",
                lambda csrf: (
                    f"""<header><h1>Continue your session</h1></header><main>
<p>Your short-lived access session has expired.</p>
<form method="post" action="/session/refresh">
<input type="hidden" name="csrf_token" value="{escape(csrf)}">
<input type="hidden" name="next" value="/account">
<button type="submit">Continue securely</button></form>
<p><a href="/logout">Sign out instead</a></p></main>"""
                ),
                purpose="refresh",
                binding_token=refresh_token,
                status_code=401,
            )
        response = RedirectResponse("/login", status_code=303)
        clear_auth_cookies(response, request_settings(request))
        return response
    company = escape(context.company.name if context.company else "Platform")
    return new_csrf_response(
        request,
        "Account",
        lambda csrf: (
            f"""<header><h1>Account</h1></header><main>
<div class="card"><p><strong>User:</strong> {escape(context.user.username)}</p>
<p><strong>Company:</strong> {company}</p>
<p><strong>Account status:</strong> {escape(context.user.account_status)}</p>
<p><strong>Session:</strong> {escape(context.session.id)}</p>
<p><strong>Expires:</strong> {escape(str(context.session.expires_at))}</p></div>
<form method="post" action="/logout"><input type="hidden" name="csrf_token" value="{escape(csrf)}">
<button type="submit">Sign out</button></form></main>"""
        ),
        purpose="logout",
        binding_token=access_token,
    )


@router.post("/session/refresh", include_in_schema=False)
def web_refresh_session(
    request: Request,
    db: DbSession,
    csrf_token: Annotated[str, Form(max_length=256)] = "",
    next: Annotated[str, Form(max_length=2048)] = "/account",
) -> RedirectResponse:
    refresh_token = request.cookies.get(REFRESH_COOKIE, "")
    verify_csrf(
        request,
        csrf_token,
        purpose="refresh",
        binding_tokens=(refresh_token,),
    )
    settings = request_settings(request)
    next_url = safe_next_url(next)
    try:
        issued = rotate_refresh_token(
            db,
            refresh_token,
            user_agent=request.headers.get("user-agent"),
            ip_address=client_ip(request),
        )
        db.commit()
    except ServiceError as exc:
        if exc.status_code == 401:
            db.commit()
        else:
            db.rollback()
        response = RedirectResponse("/login", status_code=303)
        clear_auth_cookies(response, settings)
        return response
    response = RedirectResponse(next_url, status_code=303)
    set_session_cookies(response, issued, settings)
    _delete_cookie(response, CSRF_COOKIE, settings, path="/", samesite="strict")
    return response


@router.get("/logout", response_class=HTMLResponse, include_in_schema=False)
def logout_page(request: Request) -> Response:
    binding_token = request.cookies.get(ACCESS_COOKIE) or request.cookies.get(REFRESH_COOKIE)
    if not binding_token:
        response = RedirectResponse("/login", status_code=303)
        clear_auth_cookies(response, request_settings(request))
        return response
    return new_csrf_response(
        request,
        "Sign out",
        lambda csrf: (
            f"""<header><h1>Sign out</h1></header><main>
<form method="post" action="/logout">
<input type="hidden" name="csrf_token" value="{escape(csrf)}">
<button type="submit">Sign out</button></form>
<p><a href="/account">Cancel</a></p></main>"""
        ),
        purpose="logout",
        binding_token=binding_token,
    )


@router.post("/logout", include_in_schema=False)
def web_logout(
    request: Request,
    db: DbSession,
    csrf_token: Annotated[str, Form(max_length=256)] = "",
) -> RedirectResponse:
    access = request.cookies.get(ACCESS_COOKIE)
    refresh = request.cookies.get(REFRESH_COOKIE)
    bindings = tuple(token for token in (access, refresh) if token)
    verify_csrf(
        request,
        csrf_token,
        purpose="logout",
        binding_tokens=bindings or (None,),
    )
    settings = request_settings(request)
    try:
        context = None
        if access:
            try:
                context = context_from_token(db, access)
            except ServiceError:
                context = None
        if context is not None:
            revoke_session(
                db,
                context,
                refresh_token=refresh,
            )
        elif refresh:
            revoke_refresh_token(db, refresh)
        db.commit()
    except Exception:
        # Logout is deliberately non-oracular. Local cookie removal must still
        # succeed if the database or revocation service is unavailable.
        db.rollback()
    response = RedirectResponse("/login", status_code=303)
    clear_auth_cookies(response, settings)
    return response


@router.get("/activate", response_class=HTMLResponse, include_in_schema=False)
def activate_page(request: Request, token: str | None = None) -> Response:
    settings = request_settings(request)
    if token:
        response = RedirectResponse("/activate", status_code=303)
        set_action_cookie(
            response,
            name=ACTIVATION_COOKIE,
            token=token,
            path="/activate",
            settings=settings,
        )
        _delete_cookie(response, CSRF_COOKIE, settings, path="/", samesite="strict")
        return response
    action_token = request.cookies.get(ACTIVATION_COOKIE)
    if not action_token:
        return page(
            "Activation unavailable",
            "<main><p class='error' role='alert'>This activation link is invalid or expired.</p></main>",
            status_code=400,
        )
    return new_csrf_response(
        request,
        "Activate account",
        lambda csrf: (
            f"""<header><h1>Set your password</h1></header><main><form method="post" action="/activate">
<input type="hidden" name="csrf_token" value="{escape(csrf)}">
<label>New password <input type="password" name="password" minlength="8" autocomplete="new-password" required></label>
<button type="submit">Activate account</button></form></main>"""
        ),
        purpose="activation",
        binding_token=action_token,
    )


@router.post("/activate", response_class=HTMLResponse, include_in_schema=False)
def activate_submit(
    request: Request,
    db: DbSession,
    csrf_token: Annotated[str, Form(max_length=256)] = "",
    password: Annotated[str, Form(min_length=8, max_length=128)] = "",
) -> HTMLResponse:
    token = request.cookies.get(ACTIVATION_COOKIE, "")
    verify_csrf(
        request,
        csrf_token,
        purpose="activation",
        binding_tokens=(token,),
    )
    settings = request_settings(request)
    scope_keys = auth_throttle_scope_keys(
        action="activation",
        account_identifier=hash_session_token(token),
        ip_address=client_ip(request),
    )
    try:
        check_auth_throttle(db, scope_keys)
        confirm_activation(db, token, password)
        record_auth_throttle_attempt(db, scope_keys)
        db.commit()
    except ServiceError as exc:
        db.rollback()
        if exc.status_code != 429:
            record_auth_throttle_attempt(db, scope_keys)
            db.commit()
        response = page(
            "Activation failed",
            "<main><p class='error' role='alert'>This activation link is invalid or expired.</p></main>",
            status_code=429 if exc.status_code == 429 else 400,
        )
        clear_action_cookie(
            response,
            name=ACTIVATION_COOKIE,
            path="/activate",
            settings=settings,
        )
        _delete_cookie(response, CSRF_COOKIE, settings, path="/", samesite="strict")
        return response
    response = page(
        "Account activated",
        "<main><p>Password set. You may now <a href='/login'>sign in</a>.</p></main>",
    )
    clear_action_cookie(
        response,
        name=ACTIVATION_COOKIE,
        path="/activate",
        settings=settings,
    )
    _delete_cookie(response, CSRF_COOKIE, settings, path="/", samesite="strict")
    return response


def forgot_password_form(csrf: str, workspace: str, error: str = "") -> str:
    error_html = f'<p class="error" role="alert">{escape(error)}</p>' if error else ""
    workspace_query = quote(workspace, safe="")
    return f"""<header><h1>Request password reset</h1></header><main>{error_html}
<form method="post" action="/forgot-password">
<input type="hidden" name="csrf_token" value="{escape(csrf)}">
<label>Workspace <input name="workspace_slug" value="{escape(workspace)}" required></label>
<label>Login ID or email <input name="username_or_email" autocomplete="username" required></label>
<button type="submit">Send reset link</button></form>
<p><a href="/login?workspace={workspace_query}">Back to sign in</a></p></main>"""


@router.get("/forgot-password", response_class=HTMLResponse, include_in_schema=False)
def forgot_password_page(request: Request, workspace: str = "") -> HTMLResponse:
    return new_csrf_response(
        request,
        "Request password reset",
        lambda csrf: forgot_password_form(csrf, workspace),
        purpose="forgot-password",
    )


@router.post("/forgot-password", response_class=HTMLResponse, include_in_schema=False)
def forgot_password_submit(
    request: Request,
    db: DbSession,
    csrf_token: Annotated[str, Form(max_length=256)] = "",
    workspace_slug: Annotated[str, Form(min_length=2, max_length=120)] = "",
    username_or_email: Annotated[str, Form(min_length=1, max_length=255)] = "",
) -> HTMLResponse:
    verify_csrf(request, csrf_token, purpose="forgot-password")
    settings = request_settings(request)
    scope_keys = auth_throttle_scope_keys(
        action="password_reset_request",
        account_identifier=username_or_email,
        workspace=workspace_slug,
        ip_address=client_ip(request),
    )
    try:
        check_auth_throttle(db, scope_keys)
        if settings.is_production and (not settings.smtp_host or not settings.smtp_from_email):
            raise ServiceError(503, "Password reset is temporarily unavailable.")
        user = find_password_reset_user(
            db,
            username_or_email=username_or_email,
            workspace_slug=workspace_slug,
        )
        if user and user.email:
            token, _row = create_action_token(db, user, "password_reset")
            delivered = deliver_action_token(
                email=user.email,
                purpose="password_reset",
                token=token,
                settings=settings,
            )
            if settings.is_production and not delivered:
                raise OSError("Password-reset delivery failed.")
        record_auth_throttle_attempt(db, scope_keys)
        db.commit()
    except ServiceError as exc:
        db.rollback()
        if exc.status_code != 429:
            record_auth_throttle_attempt(db, scope_keys)
            db.commit()
        if exc.status_code == 429:
            return new_csrf_response(
                request,
                "Request password reset",
                lambda csrf: forgot_password_form(
                    csrf,
                    workspace_slug,
                    "Too many requests. Please try again later.",
                ),
                purpose="forgot-password",
                status_code=429,
            )
        return page(
            "Password reset unavailable",
            "<main><p class='error' role='alert'>Password reset is temporarily unavailable.</p></main>",
            status_code=503,
        )
    except OSError:
        # Delivery errors are deliberately indistinguishable from an unknown
        # account. Roll back the unusable token but keep the generic response.
        db.rollback()
        record_auth_throttle_attempt(db, scope_keys)
        db.commit()
    response = page(
        "Password reset requested",
        """<header><h1>Check your email</h1></header><main>
<p>If the account exists, a password-reset link will be sent.</p>
<p><a href="/login">Return to sign in</a></p></main>""",
        status_code=202,
    )
    _delete_cookie(response, CSRF_COOKIE, settings, path="/", samesite="strict")
    return response


@router.get("/reset-password", response_class=HTMLResponse, include_in_schema=False)
def reset_password_page(request: Request, token: str | None = None) -> Response:
    settings = request_settings(request)
    if token:
        response = RedirectResponse("/reset-password", status_code=303)
        set_action_cookie(
            response,
            name=RESET_COOKIE,
            token=token,
            path="/reset-password",
            settings=settings,
        )
        _delete_cookie(response, CSRF_COOKIE, settings, path="/", samesite="strict")
        return response
    action_token = request.cookies.get(RESET_COOKIE)
    if not action_token:
        return page(
            "Reset unavailable",
            "<main><p class='error' role='alert'>This reset link is invalid or expired.</p></main>",
            status_code=400,
        )
    return new_csrf_response(
        request,
        "Reset password",
        lambda csrf: (
            f"""<header><h1>Reset password</h1></header><main><form method="post" action="/reset-password">
<input type="hidden" name="csrf_token" value="{escape(csrf)}">
<label>New password <input type="password" name="password" minlength="8" autocomplete="new-password" required></label>
<button type="submit">Reset password</button></form></main>"""
        ),
        purpose="password-reset",
        binding_token=action_token,
    )


@router.post("/reset-password", response_class=HTMLResponse, include_in_schema=False)
def reset_password_submit(
    request: Request,
    db: DbSession,
    csrf_token: Annotated[str, Form(max_length=256)] = "",
    password: Annotated[str, Form(min_length=8, max_length=128)] = "",
) -> HTMLResponse:
    token = request.cookies.get(RESET_COOKIE, "")
    verify_csrf(
        request,
        csrf_token,
        purpose="password-reset",
        binding_tokens=(token,),
    )
    settings = request_settings(request)
    scope_keys = auth_throttle_scope_keys(
        action="password_reset_confirm",
        account_identifier=hash_session_token(token),
        ip_address=client_ip(request),
    )
    try:
        check_auth_throttle(db, scope_keys)
        confirm_password_reset(db, token, password)
        record_auth_throttle_attempt(db, scope_keys)
        db.commit()
    except ServiceError as exc:
        db.rollback()
        if exc.status_code != 429:
            record_auth_throttle_attempt(db, scope_keys)
            db.commit()
        response = page(
            "Reset failed",
            "<main><p class='error' role='alert'>This reset link is invalid or expired.</p></main>",
            status_code=429 if exc.status_code == 429 else 400,
        )
        clear_action_cookie(
            response,
            name=RESET_COOKIE,
            path="/reset-password",
            settings=settings,
        )
        _delete_cookie(response, CSRF_COOKIE, settings, path="/", samesite="strict")
        return response
    response = page(
        "Password reset",
        "<main><p>Password reset. You may now <a href='/login'>sign in</a>.</p></main>",
    )
    clear_action_cookie(
        response,
        name=RESET_COOKIE,
        path="/reset-password",
        settings=settings,
    )
    _delete_cookie(response, CSRF_COOKIE, settings, path="/", samesite="strict")
    return response


@router.get("/store/{workspace_slug}", response_class=HTMLResponse, include_in_schema=False)
def storefront(workspace_slug: str, db: DbSession) -> HTMLResponse:
    company = db.scalar(
        select(Company).where(
            Company.slug == normalize_company_slug(workspace_slug),
            Company.status == "active",
        )
    )
    if company is None:
        raise HTTPException(status_code=404, detail="Storefront not found.")

    products = list(
        db.scalars(
            select(Product)
            .where(
                Product.company_id == company.id,
                Product.status == "active",
                Product.visibility != "hidden",
            )
            .order_by(Product.featured.desc(), Product.name)
        ).all()
    )
    vendors = {
        vendor.id: vendor
        for vendor in db.scalars(
            select(Vendor).where(Vendor.company_id == company.id, Vendor.status == "active")
        ).all()
    }
    if products:
        cards = "\n".join(
            f"""<article class="card">
  <h2>{escape(product.name)}</h2>
  <p class="muted">{escape(product.short_description or product.sku or "")}</p>
  <p class="price">PKR {(product.sale_price_minor or product.regular_price_minor) / 100:,.2f}</p>
  {f'<p><a href="/store/{quote(workspace_slug, safe="")}/vendors/{quote(vendors[product.vendor_id].slug, safe="")}">Sold by {escape(vendors[product.vendor_id].name)}</a></p>' if product.vendor_id in vendors else ""}
</article>"""
            for product in products
        )
    else:
        cards = '<p class="muted">No active products are published yet.</p>'
    return page(
        company.name,
        f"""<header><h1>{escape(company.name)}</h1></header>
<main><section class="grid">{cards}</section></main>""",
    )


@router.get(
    "/store/{workspace_slug}/vendors/{vendor_slug}",
    response_class=HTMLResponse,
    include_in_schema=False,
)
def vendor_storefront(workspace_slug: str, vendor_slug: str, db: DbSession) -> HTMLResponse:
    company = db.scalar(
        select(Company).where(
            Company.slug == normalize_company_slug(workspace_slug), Company.status == "active"
        )
    )
    if company is None:
        raise HTTPException(status_code=404, detail="Storefront not found.")
    vendor = db.scalar(
        select(Vendor).where(
            Vendor.company_id == company.id, Vendor.slug == vendor_slug, Vendor.status == "active"
        )
    )
    if vendor is None:
        raise HTTPException(status_code=404, detail="Vendor storefront not found.")
    products = list(
        db.scalars(
            select(Product)
            .where(
                Product.company_id == company.id,
                Product.vendor_id == vendor.id,
                Product.status == "active",
                Product.visibility != "hidden",
            )
            .order_by(Product.featured.desc(), Product.name)
        ).all()
    )
    cards = (
        "\n".join(
            f"""<article class="card"><h2>{escape(product.name)}</h2>
<p class="muted">{escape(product.short_description or product.sku or "")}</p>
<p class="price">PKR {(product.sale_price_minor or product.regular_price_minor) / 100:,.2f}</p></article>"""
            for product in products
        )
        or '<p class="muted">No active products are published yet.</p>'
    )
    return page(
        f"{vendor.name} | {company.name}",
        f"""<header><h1>{escape(vendor.name)}</h1><p><a href="/store/{quote(workspace_slug, safe="")}">Back to {escape(company.name)}</a></p></header>
<main><section class="grid">{cards}</section></main>""",
    )
