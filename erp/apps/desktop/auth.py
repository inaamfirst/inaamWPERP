from __future__ import annotations

from collections.abc import Mapping
from urllib.parse import urlencode, urlsplit, urlunsplit

ACCOUNT_STATUSES = ("active", "pending", "paused", "stopped")
VENDOR_STATUSES = ACCOUNT_STATUSES
VENDOR_ONBOARDING_OPTIONS = (
    ("Activation email", "activation"),
    ("Temporary password", "temporary_password"),
)
DESKTOP_PREFERENCE_KEYS = {
    "username": "authentication/username",
    "workspace": "authentication/workspace",
}
VENDOR_SELF_PERMISSIONS = frozenset(
    {
        "vendor.profile.view",
        "vendor.products.view",
        "vendor.orders.view",
        "vendor.settlements.view",
    }
)


def public_auth_url(base_url: str, route: str, workspace: str | None = None) -> str:
    if route not in {"/forgot-password", "/register"}:
        raise ValueError("Unsupported public authentication route.")
    parsed = urlsplit(base_url.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("The configured API URL is not a valid HTTP(S) address.")
    query = urlencode({"workspace": workspace.strip()}) if workspace and workspace.strip() else ""
    return urlunsplit((parsed.scheme, parsed.netloc, route, query, ""))


def role_names_for_session(
    current_session: Mapping[str, object],
    permissions: list[str],
    vendor: Mapping[str, object] | None = None,
) -> list[str]:
    user = current_session.get("user")
    if isinstance(user, Mapping):
        supplied = user.get("role_names")
        if isinstance(supplied, list):
            names = sorted({str(value) for value in supplied if str(value).strip()})
            if names:
                return names
    granted = set(permissions)
    administrator_markers = {
        "identity.manage_users",
        "identity.manage_roles",
        "tenancy.manage_companies",
        "vendors.manage",
    }
    if administrator_markers.issubset(granted):
        return ["Administrator"]
    if VENDOR_SELF_PERMISSIONS & granted:
        return ["Vendor"]
    return ["Custom staff"] if granted else []


def should_load_vendor_self(roles: list[str], permissions: list[str] | set[str]) -> bool:
    role_set = set(roles)
    return (
        "vendor.profile.view" in permissions
        and "Vendor" in role_set
        and "Administrator" not in role_set
    )


def navigation_visibility(
    permissions: list[str],
    *,
    must_change_password: bool = False,
) -> dict[str, bool]:
    if must_change_password:
        return {name: False for name in _NAVIGATION_REQUIREMENTS}
    granted = set(permissions)
    visible: dict[str, bool] = {}
    for name, required in _NAVIGATION_REQUIREMENTS.items():
        visible[name] = not required or bool(required & granted)
    return visible


_NAVIGATION_REQUIREMENTS: dict[str, frozenset[str]] = {
    "Dashboard": frozenset({"reports.view", "vendor.profile.view"}),
    "Products": frozenset({"catalog.view"}),
    "Customers": frozenset({"customers.view"}),
    "Inventory": frozenset({"inventory.view"}),
    "Orders": frozenset({"orders.view"}),
    "WooCommerce": frozenset({"woocommerce.view"}),
    "Marketplace": frozenset({"vendors.view", *VENDOR_SELF_PERMISSIONS}),
    "Accounting": frozenset({"accounting.view"}),
    "Settings": frozenset(),
    "Admin": frozenset(
        {
            "identity.view_users",
            "identity.manage_users",
            "identity.manage_roles",
            "tenancy.view_companies",
            "tenancy.manage_companies",
        }
    ),
}


def session_display_lines(
    auth_payload: Mapping[str, object],
    current_session: Mapping[str, object],
    *,
    remembered: bool,
    roles: list[str],
    vendor: Mapping[str, object] | None = None,
) -> list[str]:
    user_value = current_session.get("user")
    user = user_value if isinstance(user_value, Mapping) else {}
    company_value = current_session.get("company")
    company = company_value if isinstance(company_value, Mapping) else {}
    lines = [
        f"User: {user.get('username') or 'unknown'}",
        f"Full name: {user.get('full_name') or 'not set'}",
        f"Company: {company.get('name') or 'Platform'}",
        f"Workspace: {company.get('slug') or 'not applicable'}",
        f"Account status: {user.get('account_status') or 'unknown'}",
        f"Roles: {', '.join(roles) if roles else 'none'}",
        f"Login time: {current_session.get('session_created_at') or 'unknown'}",
        (
            "Access expires: {}".format(
                auth_payload.get("expires_at")
                or current_session.get("session_expires_at")
                or "unknown"
            )
        ),
        f"Refresh expires: {auth_payload.get('refresh_expires_at') or 'not available'}",
        f"Remember Me: {'enabled' if remembered else 'disabled'}",
        (
            "Password change required: "
            f"{'yes' if bool(user.get('must_change_password')) else 'no'}"
        ),
    ]
    if vendor is not None:
        lines.extend(
            [
                f"Vendor: {vendor.get('name') or 'unknown'}",
                (
                    "Vendor access status: "
                    f"{vendor.get('access_status') or vendor.get('status') or 'unknown'}"
                ),
            ]
        )
    return lines


def build_vendor_account_payload(
    *,
    business_name: str,
    username: str,
    email: str | None,
    contact_name: str | None,
    phone: str | None,
    onboarding: str,
    temporary_password: str | None,
    default_commission_bps: int,
) -> dict[str, object]:
    if onboarding not in {value for _label, value in VENDOR_ONBOARDING_OPTIONS}:
        raise ValueError("Choose a valid vendor onboarding method.")
    if not business_name.strip() or not username.strip():
        raise ValueError("Business name and login ID are required.")
    use_activation = onboarding == "activation"
    if use_activation and not (email or "").strip():
        raise ValueError("An email address is required for activation onboarding.")
    if not use_activation and len(temporary_password or "") < 8:
        raise ValueError("A temporary password of at least 8 characters is required.")
    payload: dict[str, object] = {
        "business_name": business_name.strip(),
        "username": username.strip(),
        "use_activation": use_activation,
        "default_commission_bps": default_commission_bps,
    }
    for key, value in (
        ("email", email),
        ("contact_name", contact_name),
        ("phone", phone),
    ):
        if value and value.strip():
            payload[key] = value.strip()
    if not use_activation:
        payload["password"] = temporary_password or ""
    return payload


def vendor_onboarding_result_lines(result: Mapping[str, object]) -> list[str]:
    vendor_value = result.get("vendor")
    vendor = vendor_value if isinstance(vendor_value, Mapping) else {}
    user_value = result.get("user")
    user = user_value if isinstance(user_value, Mapping) else {}
    return [
        f"Vendor: {vendor.get('name') or 'unknown'}",
        f"Vendor access: {vendor.get('access_status') or vendor.get('status') or 'unknown'}",
        f"Linked login ID: {user.get('username') or 'unknown'}",
        f"Linked user ID: {user.get('id') or 'unknown'}",
        f"Account status: {user.get('account_status') or 'unknown'}",
        f"Onboarding: {result.get('onboarding_method') or 'unknown'}",
        f"Activation delivery: {result.get('activation_delivery') or 'not requested'}",
        (
            "Password change required: "
            f"{'yes' if bool(user.get('must_change_password')) else 'no'}"
        ),
    ]


def safe_login_error(status_code: int) -> str:
    if status_code == 429:
        return "Too many sign-in attempts. Please try again later."
    if status_code == 0:
        return "The authentication service is unavailable. Check the API connection."
    return "Unable to sign in with those credentials or access this workspace."
