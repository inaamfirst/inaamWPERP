from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class SetupStatus(BaseModel):
    is_configured: bool


class FirstUseSetupRequest(BaseModel):
    company_name: str = Field(min_length=2, max_length=255)
    workspace_slug: str | None = Field(
        default=None,
        min_length=2,
        max_length=120,
        pattern=r"^[a-z0-9][a-z0-9-]*[a-z0-9]$",
    )
    username: str = Field(min_length=3, max_length=120, pattern=r"^[A-Za-z0-9_.-]+$")
    password: str = Field(min_length=8, max_length=128)
    full_name: str | None = Field(default=None, max_length=255)
    email: str | None = Field(default=None, max_length=255)


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=120)
    password: str = Field(min_length=1, max_length=128)
    company_id: str | None = Field(default=None, max_length=36)
    workspace_slug: str | None = Field(
        default=None,
        min_length=2,
        max_length=120,
        pattern=r"^[a-z0-9][a-z0-9-]*[a-z0-9]$",
    )
    remember_me: bool = False
    # Old clients omit this field and retain the historical access-session TTL.
    # Refresh-aware clients opt in to short-lived access tokens.
    supports_refresh: bool = False


class RefreshRequest(BaseModel):
    refresh_token: str | None = Field(default=None, min_length=20, max_length=512)


class LogoutRequest(BaseModel):
    refresh_token: str | None = Field(default=None, min_length=20, max_length=512)
    all_sessions: bool = False


class PasswordChangeRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=8, max_length=128)


class PasswordResetRequest(BaseModel):
    username_or_email: str = Field(min_length=1, max_length=255)
    workspace_slug: str = Field(
        min_length=2,
        max_length=120,
        pattern=r"^[a-z0-9][a-z0-9-]*[a-z0-9]$",
    )


class PasswordResetConfirm(BaseModel):
    token: str = Field(min_length=20, max_length=512)
    new_password: str = Field(min_length=8, max_length=128)


class ActivationConfirm(BaseModel):
    token: str = Field(min_length=20, max_length=512)
    password: str | None = Field(default=None, min_length=8, max_length=128)


class VendorRegistrationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workspace_slug: str = Field(
        min_length=2,
        max_length=120,
        pattern=r"^[a-z0-9][a-z0-9-]*[a-z0-9]$",
    )
    business_name: str = Field(min_length=2, max_length=255)
    username: str = Field(min_length=3, max_length=120, pattern=r"^[A-Za-z0-9_.-]+$")
    email: str = Field(min_length=3, max_length=255)
    password: str = Field(min_length=8, max_length=128)
    contact_name: str | None = Field(default=None, max_length=255)
    phone: str | None = Field(default=None, max_length=80)


class UserRegistrationRequest(BaseModel):
    """Public staff-account request. Roles are deliberately not accepted here."""

    model_config = ConfigDict(extra="forbid")

    workspace_slug: str = Field(
        min_length=2,
        max_length=120,
        pattern=r"^[a-z0-9][a-z0-9-]*[a-z0-9]$",
    )
    username: str = Field(min_length=3, max_length=120, pattern=r"^[A-Za-z0-9_.-]+$")
    email: str = Field(min_length=3, max_length=255)
    password: str = Field(min_length=8, max_length=128)
    full_name: str | None = Field(default=None, max_length=255)


class RegistrationResponse(BaseModel):
    vendor_id: str
    user_id: str
    account_status: str
    vendor_status: str
    message: str


class UserRegistrationResponse(BaseModel):
    user_id: str
    account_status: str
    message: str


class CompanyOut(BaseModel):
    id: str
    name: str
    slug: str
    legal_name: str | None = None
    status: str
    created_at: datetime | None = None
    updated_at: datetime | None = None


class CompanyCreate(BaseModel):
    name: str = Field(min_length=2, max_length=255)
    slug: str | None = Field(
        default=None,
        min_length=2,
        max_length=120,
        pattern=r"^[a-z0-9][a-z0-9-]*[a-z0-9]$",
    )
    legal_name: str | None = Field(default=None, max_length=255)


class CompanyUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=255)
    slug: str | None = Field(
        default=None,
        min_length=2,
        max_length=120,
        pattern=r"^[a-z0-9][a-z0-9-]*[a-z0-9]$",
    )
    legal_name: str | None = Field(default=None, max_length=255)
    status: str | None = Field(default=None, min_length=3, max_length=32)


class UserOut(BaseModel):
    id: str
    company_id: str | None
    username: str
    email: str | None
    full_name: str | None
    is_active: bool
    account_status: str = "active"
    must_change_password: bool = False
    password_changed_at: datetime | None = None
    last_login_at: datetime | None = None
    role_ids: list[str] = Field(default_factory=list)
    role_names: list[str] = Field(default_factory=list)
    created_at: datetime | None = None
    updated_at: datetime | None = None


class UserCreate(BaseModel):
    username: str = Field(min_length=3, max_length=120, pattern=r"^[A-Za-z0-9_.-]+$")
    password: str = Field(min_length=8, max_length=128)
    email: str | None = Field(default=None, max_length=255)
    full_name: str | None = Field(default=None, max_length=255)
    role_ids: list[str] = Field(default_factory=list, max_length=20)
    account_status: Literal["active", "pending", "paused", "stopped"] = "active"
    must_change_password: bool = False


class UserUpdate(BaseModel):
    username: str | None = Field(
        default=None,
        min_length=3,
        max_length=120,
        pattern=r"^[A-Za-z0-9_.-]+$",
    )
    password: str | None = Field(default=None, min_length=8, max_length=128)
    email: str | None = Field(default=None, max_length=255)
    full_name: str | None = Field(default=None, max_length=255)
    is_active: bool | None = None
    role_ids: list[str] | None = Field(default=None, max_length=20)
    account_status: Literal["active", "pending", "paused", "stopped"] | None = None
    must_change_password: bool | None = None


class UserPasswordReset(BaseModel):
    password: str = Field(min_length=8, max_length=128)


class RegistrationApprovalRequest(BaseModel):
    """Administrator-selected roles for a pending staff registration."""

    role_ids: list[str] = Field(default_factory=list, max_length=20)


class RegistrationRejectionRequest(BaseModel):
    reason: str | None = Field(default=None, max_length=500)


class RoleCreate(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    description: str | None = Field(default=None, max_length=5000)
    permissions: list[str] = Field(default_factory=list, max_length=500)


class RoleUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=120)
    description: str | None = Field(default=None, max_length=5000)
    permissions: list[str] | None = Field(default=None, max_length=500)


class AuthResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_at: datetime
    refresh_token: str | None = None
    refresh_expires_at: datetime | None = None
    session_id: str
    user: UserOut
    company: CompanyOut | None
    permissions: list[str]


class CurrentUserResponse(BaseModel):
    user: UserOut
    company: CompanyOut | None
    permissions: list[str]
    session_id: str
    session_created_at: datetime
    session_expires_at: datetime
    session_user_agent: str | None = None


class RoleOut(BaseModel):
    id: str
    company_id: str | None
    name: str
    description: str | None
    permissions: list[str]


class PermissionOut(BaseModel):
    key: str
    description: str | None


class SettingOut(BaseModel):
    key: str
    value: dict[str, Any]
    updated_at: datetime


class PushSubscriptionKeys(BaseModel):
    p256dh: str = Field(min_length=16, max_length=512)
    auth: str = Field(min_length=8, max_length=512)


class PushSubscriptionCreate(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    endpoint: str = Field(min_length=20, max_length=4096)
    keys: PushSubscriptionKeys
    expiration_time: int | None = Field(default=None, ge=0, alias="expirationTime")
    user_agent: str | None = Field(default=None, max_length=500)
    device_label: str | None = Field(default=None, max_length=120)

    @field_validator("endpoint")
    @classmethod
    def validate_endpoint(cls, value: str) -> str:
        if not value.startswith(("https://", "http://")):
            raise ValueError("Push endpoint must be an HTTP(S) URL.")
        return value


class PushSubscriptionOut(BaseModel):
    id: str
    endpoint: str
    expiration_at: datetime | None
    user_agent: str | None
    device_label: str | None
    is_active: bool
    last_seen_at: datetime | None
    created_at: datetime
    updated_at: datetime


class PushConfigOut(BaseModel):
    enabled: bool
    public_key: str | None


class PushNotificationOut(BaseModel):
    id: str
    event_type: str
    order_id: str | None
    vendor_id: str | None
    title: str
    body: str
    target_route: str
    status: str
    attempts: int
    scheduled_at: datetime
    sent_at: datetime | None
    failed_at: datetime | None
    last_error: str | None
    created_at: datetime
    updated_at: datetime


class SettingUpdateRequest(BaseModel):
    value: dict[str, Any]


class AuditLogOut(BaseModel):
    id: str
    company_id: str | None
    user_id: str | None
    action: str
    entity_type: str | None
    entity_id: str | None
    metadata: dict[str, Any]
    created_at: datetime


class CategoryCreate(BaseModel):
    name: str = Field(min_length=2, max_length=255)
    slug: str | None = Field(default=None, min_length=2, max_length=160)
    parent_id: str | None = Field(default=None, max_length=36)
    description: str | None = Field(default=None, max_length=5000)


class CategoryUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=255)
    slug: str | None = Field(default=None, min_length=2, max_length=160)
    parent_id: str | None = Field(default=None, max_length=36)
    description: str | None = Field(default=None, max_length=5000)
    is_active: bool | None = None


class CategoryOut(BaseModel):
    id: str
    company_id: str
    parent_id: str | None
    name: str
    slug: str
    description: str | None
    is_active: bool
    created_at: datetime
    updated_at: datetime


class BrandCreate(BaseModel):
    name: str = Field(min_length=2, max_length=255)
    slug: str | None = Field(default=None, min_length=2, max_length=160)
    description: str | None = Field(default=None, max_length=5000)


class BrandUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=255)
    slug: str | None = Field(default=None, min_length=2, max_length=160)
    description: str | None = Field(default=None, max_length=5000)
    is_active: bool | None = None


class BrandOut(BaseModel):
    id: str
    company_id: str
    name: str
    slug: str
    description: str | None
    is_active: bool
    created_at: datetime
    updated_at: datetime


class ProductTagCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    slug: str | None = Field(default=None, min_length=1, max_length=120)


class ProductTagOut(BaseModel):
    id: str
    company_id: str
    name: str
    slug: str
    is_active: bool
    created_at: datetime
    updated_at: datetime


class ProductVariantCreate(BaseModel):
    id: str | None = Field(default=None, max_length=36)
    name: str | None = Field(default=None, max_length=255)
    sku: str | None = Field(default=None, min_length=1, max_length=120)
    barcode: str | None = Field(default=None, max_length=120)
    price_minor: int = Field(default=0, ge=0)
    cost_minor: int | None = Field(default=None, ge=0)
    currency: str = Field(default="PKR", min_length=3, max_length=3)
    attributes: dict[str, Any] = Field(default_factory=dict)
    sale_price_minor: int | None = Field(default=None, ge=0)
    manage_stock: bool | None = None
    stock_quantity: int | None = Field(default=None, ge=0)
    stock_status: str | None = Field(default=None, max_length=40)
    backorders: str | None = Field(default=None, max_length=20)
    weight: str | None = Field(default=None, max_length=40)
    length: str | None = Field(default=None, max_length=40)
    width: str | None = Field(default=None, max_length=40)
    height: str | None = Field(default=None, max_length=40)
    shipping_class: str | None = Field(default=None, max_length=120)
    description: str | None = Field(default=None, max_length=10000)
    image_url: str | None = Field(default=None, max_length=2000)
    metadata: dict[str, Any] = Field(default_factory=dict)
    is_active: bool = True


class ProductVariantOut(BaseModel):
    id: str
    product_id: str
    name: str | None
    sku: str | None
    barcode: str | None
    price_minor: int
    cost_minor: int | None
    currency: str
    attributes: dict[str, Any]
    sale_price_minor: int | None = None
    manage_stock: bool | None = None
    stock_quantity: int | None = None
    stock_status: str | None = None
    backorders: str | None = None
    weight: str | None = None
    length: str | None = None
    width: str | None = None
    height: str | None = None
    shipping_class: str | None = None
    description: str | None = None
    image_url: str | None = None
    metadata: dict[str, Any]
    is_active: bool


class ProductImageCreate(BaseModel):
    id: str | None = Field(default=None, max_length=36)
    url: str = Field(min_length=4, max_length=2000)
    variant_id: str | None = Field(default=None, max_length=36)
    external_id: str | None = Field(default=None, max_length=120)
    name: str | None = Field(default=None, max_length=255)
    alt_text: str | None = Field(default=None, max_length=255)
    sort_order: int = Field(default=0, ge=0)


class ProductImageOut(BaseModel):
    id: str
    product_id: str
    variant_id: str | None
    external_id: str | None
    url: str
    name: str | None
    alt_text: str | None
    sort_order: int
    sync_status: str
    last_synced_at: datetime | None


class ProductVideoCreate(BaseModel):
    id: str | None = Field(default=None, max_length=36)
    url: str = Field(min_length=8, max_length=2000)
    name: str | None = Field(default=None, max_length=255)
    sort_order: int = Field(default=0, ge=0)


class ProductVideoOut(BaseModel):
    id: str
    product_id: str
    source_type: str
    url: str
    name: str | None
    sort_order: int
    external_id: str | None
    remote_url: str | None
    sync_status: str
    last_synced_at: datetime | None
    created_at: datetime
    updated_at: datetime


class ProductCreate(BaseModel):
    name: str = Field(min_length=2, max_length=255)
    slug: str | None = Field(default=None, min_length=2, max_length=160)
    sku: str | None = Field(default=None, min_length=1, max_length=120)
    barcode: str | None = Field(default=None, max_length=120)
    vendor_id: str | None = Field(default=None, max_length=36)
    product_type: str = Field(default="simple", min_length=3, max_length=40)
    status: str = Field(default="active", min_length=3, max_length=40)
    category_id: str | None = Field(default=None, max_length=36)
    category_ids: list[str] = Field(default_factory=list, max_length=50)
    brand_id: str | None = Field(default=None, max_length=36)
    description: str | None = Field(default=None, max_length=10000)
    short_description: str | None = Field(default=None, max_length=10000)
    seo_title: str | None = Field(default=None, max_length=255)
    seo_description: str | None = Field(default=None, max_length=5000)
    visibility: str = Field(default="visible", max_length=40)
    featured: bool = False
    global_unique_id: str | None = Field(default=None, max_length=120)
    regular_price_minor: int = Field(default=0, ge=0)
    sale_price_minor: int | None = Field(default=None, ge=0)
    sale_start_at: datetime | None = None
    sale_end_at: datetime | None = None
    tax_status: str = Field(default="taxable", max_length=40)
    tax_class: str | None = Field(default=None, max_length=120)
    manage_stock: bool = False
    stock_quantity: int | None = Field(default=None, ge=0)
    stock_status: str = Field(default="instock", max_length=40)
    backorders: str = Field(default="no", max_length=20)
    sold_individually: bool = False
    weight: str | None = Field(default=None, max_length=40)
    length: str | None = Field(default=None, max_length=40)
    width: str | None = Field(default=None, max_length=40)
    height: str | None = Field(default=None, max_length=40)
    shipping_class: str | None = Field(default=None, max_length=120)
    reviews_allowed: bool = True
    purchase_note: str | None = Field(default=None, max_length=5000)
    menu_order: int = 0
    tags: list[str] = Field(default_factory=list, max_length=50)
    upsell_ids: list[str] = Field(default_factory=list, max_length=100)
    cross_sell_ids: list[str] = Field(default_factory=list, max_length=100)
    grouped_product_ids: list[str] = Field(default_factory=list, max_length=100)
    attributes: list[dict[str, Any]] = Field(default_factory=list, max_length=100)
    default_attributes: list[dict[str, Any]] = Field(default_factory=list, max_length=100)
    custom_metadata: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)
    variants: list[ProductVariantCreate] = Field(default_factory=list, max_length=100)
    images: list[ProductImageCreate] = Field(default_factory=list, max_length=100)
    videos: list[ProductVideoCreate] = Field(default_factory=list, max_length=10)


class ProductUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=255)
    slug: str | None = Field(default=None, min_length=2, max_length=160)
    sku: str | None = Field(default=None, min_length=1, max_length=120)
    barcode: str | None = Field(default=None, max_length=120)
    vendor_id: str | None = Field(default=None, max_length=36)
    product_type: str | None = Field(default=None, min_length=3, max_length=40)
    status: str | None = Field(default=None, min_length=3, max_length=40)
    category_id: str | None = Field(default=None, max_length=36)
    category_ids: list[str] | None = Field(default=None, max_length=50)
    brand_id: str | None = Field(default=None, max_length=36)
    description: str | None = Field(default=None, max_length=10000)
    short_description: str | None = Field(default=None, max_length=10000)
    seo_title: str | None = Field(default=None, max_length=255)
    seo_description: str | None = Field(default=None, max_length=5000)
    visibility: str | None = Field(default=None, max_length=40)
    featured: bool | None = None
    global_unique_id: str | None = Field(default=None, max_length=120)
    regular_price_minor: int | None = Field(default=None, ge=0)
    sale_price_minor: int | None = Field(default=None, ge=0)
    sale_start_at: datetime | None = None
    sale_end_at: datetime | None = None
    tax_status: str | None = Field(default=None, max_length=40)
    tax_class: str | None = Field(default=None, max_length=120)
    manage_stock: bool | None = None
    stock_quantity: int | None = Field(default=None, ge=0)
    stock_status: str | None = Field(default=None, max_length=40)
    backorders: str | None = Field(default=None, max_length=20)
    sold_individually: bool | None = None
    weight: str | None = Field(default=None, max_length=40)
    length: str | None = Field(default=None, max_length=40)
    width: str | None = Field(default=None, max_length=40)
    height: str | None = Field(default=None, max_length=40)
    shipping_class: str | None = Field(default=None, max_length=120)
    reviews_allowed: bool | None = None
    purchase_note: str | None = Field(default=None, max_length=5000)
    menu_order: int | None = None
    tags: list[str] | None = Field(default=None, max_length=50)
    upsell_ids: list[str] | None = Field(default=None, max_length=100)
    cross_sell_ids: list[str] | None = Field(default=None, max_length=100)
    grouped_product_ids: list[str] | None = Field(default=None, max_length=100)
    attributes: list[dict[str, Any]] | None = Field(default=None, max_length=100)
    default_attributes: list[dict[str, Any]] | None = Field(default=None, max_length=100)
    custom_metadata: dict[str, Any] | None = None
    variants: list[ProductVariantCreate] | None = Field(default=None, max_length=100)
    images: list[ProductImageCreate] | None = Field(default=None, max_length=100)
    videos: list[ProductVideoCreate] | None = Field(default=None, max_length=10)
    metadata: dict[str, Any] | None = None


class ProductCodeSuggestionOut(BaseModel):
    sku: str
    barcode: str


class ProductOut(BaseModel):
    id: str
    company_id: str
    category_id: str | None
    brand_id: str | None
    vendor_id: str | None
    category_ids: list[str]
    name: str
    slug: str
    sku: str | None
    barcode: str | None
    product_type: str
    status: str
    description: str | None
    short_description: str | None = None
    seo_title: str | None
    seo_description: str | None
    visibility: str
    featured: bool
    global_unique_id: str | None = None
    regular_price_minor: int
    sale_price_minor: int | None = None
    sale_start_at: datetime | None = None
    sale_end_at: datetime | None = None
    tax_status: str
    tax_class: str | None = None
    manage_stock: bool
    stock_quantity: int | None = None
    stock_status: str
    backorders: str
    sold_individually: bool
    weight: str | None = None
    length: str | None = None
    width: str | None = None
    height: str | None = None
    shipping_class: str | None = None
    reviews_allowed: bool
    purchase_note: str | None = None
    menu_order: int
    tags: list[str]
    upsell_ids: list[str]
    cross_sell_ids: list[str]
    grouped_product_ids: list[str]
    attributes: list[dict[str, Any]]
    default_attributes: list[dict[str, Any]]
    custom_metadata: dict[str, Any]
    metadata: dict[str, Any]
    variants: list[ProductVariantOut]
    images: list[ProductImageOut]
    videos: list[ProductVideoOut]
    created_at: datetime
    updated_at: datetime


class WarehouseCreate(BaseModel):
    code: str = Field(min_length=2, max_length=40, pattern=r"^[A-Za-z0-9_-]+$")
    name: str = Field(min_length=2, max_length=255)
    address: str | None = Field(default=None, max_length=5000)


class WarehouseUpdate(BaseModel):
    code: str | None = Field(default=None, min_length=2, max_length=40, pattern=r"^[A-Za-z0-9_-]+$")
    name: str | None = Field(default=None, min_length=2, max_length=255)
    address: str | None = Field(default=None, max_length=5000)
    is_active: bool | None = None


class WarehouseOut(BaseModel):
    id: str
    company_id: str
    code: str
    name: str
    address: str | None
    is_active: bool
    created_at: datetime
    updated_at: datetime


class StockMovementCreate(BaseModel):
    movement_type: str = Field(min_length=3, max_length=40)
    warehouse_id: str = Field(min_length=1, max_length=36)
    product_id: str = Field(min_length=1, max_length=36)
    variant_id: str | None = Field(default=None, max_length=36)
    quantity: int | None = Field(default=None, ge=1)
    quantity_delta: int | None = None
    reference_type: str | None = Field(default=None, max_length=80)
    reference_id: str | None = Field(default=None, max_length=120)
    reason: str | None = Field(default=None, max_length=5000)
    metadata: dict[str, Any] = Field(default_factory=dict)
    occurred_at: datetime | None = None


class StockMovementOut(BaseModel):
    id: str
    company_id: str
    warehouse_id: str
    product_id: str
    variant_id: str | None
    movement_type: str
    quantity_delta: int
    reference_type: str | None
    reference_id: str | None
    transfer_group_id: str | None
    reason: str | None
    metadata: dict[str, Any]
    created_by_id: str | None
    occurred_at: datetime
    created_at: datetime


class StockLevelOut(BaseModel):
    company_id: str
    warehouse_id: str
    product_id: str
    variant_id: str | None
    quantity_on_hand: int


class CustomerAddressCreate(BaseModel):
    label: str | None = Field(default=None, max_length=80)
    recipient_name: str | None = Field(default=None, max_length=255)
    phone: str | None = Field(default=None, max_length=80)
    line1: str = Field(min_length=2, max_length=255)
    line2: str | None = Field(default=None, max_length=255)
    city: str | None = Field(default=None, max_length=120)
    state: str | None = Field(default=None, max_length=120)
    postal_code: str | None = Field(default=None, max_length=40)
    country: str = Field(default="PK", min_length=2, max_length=2)
    is_default: bool = False


class CustomerAddressOut(BaseModel):
    id: str
    customer_id: str
    label: str | None
    recipient_name: str | None
    phone: str | None
    line1: str
    line2: str | None
    city: str | None
    state: str | None
    postal_code: str | None
    country: str
    is_default: bool


class CustomerNoteCreate(BaseModel):
    note: str = Field(min_length=2, max_length=5000)


class CustomerNoteOut(BaseModel):
    id: str
    customer_id: str
    created_by_id: str | None
    note: str
    created_at: datetime


class CustomerCreate(BaseModel):
    full_name: str = Field(min_length=2, max_length=255)
    source_channel: Literal["pos", "woocommerce", "manual", "legacy"] = "legacy"
    email: str | None = Field(default=None, max_length=255)
    phone: str | None = Field(default=None, max_length=80)
    status: str = Field(default="active", min_length=3, max_length=40)
    credit_limit_minor: int = Field(default=0, ge=0)
    metadata: dict[str, Any] = Field(default_factory=dict)
    addresses: list[CustomerAddressCreate] = Field(default_factory=list, max_length=20)
    tags: list[str] = Field(default_factory=list, max_length=50)
    opening_note: str | None = Field(default=None, min_length=2, max_length=5000)


class CustomerUpdate(BaseModel):
    full_name: str | None = Field(default=None, min_length=2, max_length=255)
    email: str | None = Field(default=None, max_length=255)
    phone: str | None = Field(default=None, max_length=80)
    status: str | None = Field(default=None, min_length=3, max_length=40)
    credit_limit_minor: int | None = Field(default=None, ge=0)
    metadata: dict[str, Any] | None = None
    tags: list[str] | None = Field(default=None, max_length=50)


class CustomerOut(BaseModel):
    id: str
    company_id: str
    full_name: str
    source_channel: str
    email: str | None
    phone: str | None
    status: str
    credit_limit_minor: int
    metadata: dict[str, Any]
    addresses: list[CustomerAddressOut]
    tags: list[str]
    notes: list[CustomerNoteOut]
    created_at: datetime
    updated_at: datetime


class OrderItemCreate(BaseModel):
    product_id: str = Field(min_length=1, max_length=36)
    variant_id: str | None = Field(default=None, max_length=36)
    quantity: int = Field(ge=1)
    unit_price_minor: int | None = Field(default=None, ge=0)
    name: str | None = Field(default=None, max_length=255)
    sku: str | None = Field(default=None, max_length=120)
    metadata: dict[str, Any] = Field(default_factory=dict)


class OrderItemOut(BaseModel):
    id: str
    product_id: str
    variant_id: str | None
    vendor_id: str | None
    sku: str | None
    name: str
    quantity: int
    unit_price_minor: int
    line_total_minor: int
    metadata: dict[str, Any]


class OrderCreate(BaseModel):
    customer_id: str = Field(min_length=1, max_length=36)
    currency: str = Field(default="PKR", min_length=3, max_length=3)
    discount_minor: int = Field(default=0, ge=0)
    tax_minor: int = Field(default=0, ge=0)
    shipping_minor: int = Field(default=0, ge=0)
    notes: str | None = Field(default=None, max_length=5000)
    metadata: dict[str, Any] = Field(default_factory=dict)
    items: list[OrderItemCreate] = Field(min_length=1, max_length=200)


class OrderStatusChange(BaseModel):
    status: str = Field(min_length=3, max_length=40)
    reason: str | None = Field(default=None, max_length=5000)


class PaymentCreate(BaseModel):
    amount_minor: int = Field(ge=1)
    currency: str = Field(default="PKR", min_length=3, max_length=3)
    method: str = Field(min_length=2, max_length=80)
    status: str = Field(default="paid", min_length=3, max_length=40)
    reference: str | None = Field(default=None, max_length=160)
    paid_at: datetime | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class PaymentOut(BaseModel):
    id: str
    order_id: str
    amount_minor: int
    currency: str
    method: str
    status: str
    reference: str | None
    paid_at: datetime | None
    metadata: dict[str, Any]
    created_at: datetime


class PosSaleCreate(BaseModel):
    customer_id: str | None = None
    customer_name: str | None = Field(default=None, max_length=255)
    warehouse_id: str
    currency: str = Field(default="PKR", min_length=3, max_length=3)
    items: list[OrderItemCreate] = Field(min_length=1, max_length=200)
    discount_minor: int = Field(default=0, ge=0)
    tax_minor: int = Field(default=0, ge=0)
    notes: str | None = Field(default=None, max_length=5000)
    payments: list[PaymentCreate] = Field(default_factory=list, max_length=20)
    idempotency_key: str | None = Field(default=None, max_length=255)


class ProductChannelListingCreate(BaseModel):
    channel: Literal["woocommerce"] = "woocommerce"
    listing_status: Literal["private", "draft", "published", "paused"] = "private"
    channel_sku: str | None = Field(default=None, max_length=120)
    price_minor: int | None = Field(default=None, ge=0)


class ProductChannelListingOut(BaseModel):
    id: str
    product_id: str
    vendor_id: str | None
    channel: str
    listing_status: str
    channel_sku: str | None
    price_minor: int | None
    external_id: str | None
    sync_status: str
    last_synced_at: datetime | None
    created_at: datetime
    updated_at: datetime


class StockReservationCreate(BaseModel):
    warehouse_id: str
    product_id: str
    variant_id: str | None = None
    quantity: int = Field(gt=0)
    source_type: Literal["woocommerce", "pos"] = "woocommerce"
    source_id: str = Field(min_length=1, max_length=120)
    idempotency_key: str = Field(min_length=1, max_length=255)


class StockReservationOut(BaseModel):
    id: str
    warehouse_id: str
    product_id: str
    variant_id: str | None
    source_type: str
    source_id: str
    quantity: int
    status: str
    idempotency_key: str
    released_at: datetime | None
    created_at: datetime


class OrderStatusHistoryOut(BaseModel):
    id: str
    order_id: str
    from_status: str | None
    to_status: str
    changed_by_id: str | None
    reason: str | None
    created_at: datetime


class OrderOut(BaseModel):
    id: str
    company_id: str
    customer_id: str
    order_number: str
    sales_channel: str
    order_source: str
    external_order_id: str | None
    reservation_status: str
    status: str
    currency: str
    subtotal_minor: int
    discount_minor: int
    tax_minor: int
    shipping_minor: int
    total_minor: int
    paid_minor: int
    payment_status: str
    notes: str | None
    metadata: dict[str, Any]
    items: list[OrderItemOut]
    payments: list[PaymentOut]
    status_history: list[OrderStatusHistoryOut]
    created_at: datetime
    updated_at: datetime


DeliveryStatus = Literal[
    "assigned",
    "picked_up",
    "out_for_delivery",
    "delivered",
    "failed",
    "cancelled",
]


class DeliveryAssignmentCreate(BaseModel):
    order_id: str = Field(min_length=1, max_length=36)
    rider_user_id: str = Field(min_length=1, max_length=36)


class DeliveryAssignmentUpdate(BaseModel):
    rider_user_id: str = Field(min_length=1, max_length=36)


class DeliveryStatusChange(BaseModel):
    status: DeliveryStatus
    reason: str | None = Field(default=None, max_length=5000)


class DeliveryStatusHistoryOut(BaseModel):
    id: str
    delivery_assignment_id: str
    from_status: str | None
    to_status: str
    changed_by_id: str | None
    reason: str | None
    created_at: datetime


class DeliveryAssignmentOut(BaseModel):
    id: str
    company_id: str
    order_id: str
    order_number: str
    order_status: str
    order_total_minor: int
    payment_status: str
    rider_user_id: str
    rider_username: str | None
    rider_name: str | None
    status: DeliveryStatus
    recipient_name: str
    recipient_phone: str | None
    address_line1: str
    address_line2: str | None
    city: str | None
    state: str | None
    postal_code: str | None
    country: str
    picked_up_at: datetime | None
    out_for_delivery_at: datetime | None
    delivered_at: datetime | None
    failed_at: datetime | None
    failure_reason: str | None
    created_at: datetime
    updated_at: datetime
    history: list[DeliveryStatusHistoryOut] = Field(default_factory=list)


class DeliveryRiderOut(BaseModel):
    id: str
    username: str
    full_name: str | None
    is_active: bool


class CODCollectionCreate(BaseModel):
    delivery_assignment_id: str = Field(min_length=1, max_length=36)
    collected_minor: int = Field(ge=1)
    receipt_reference: str = Field(min_length=2, max_length=160)
    proof_reference: str = Field(min_length=2, max_length=1000)
    idempotency_key: str = Field(min_length=3, max_length=255)
    metadata: dict[str, Any] = Field(default_factory=dict)


class CODReconciliationRequest(BaseModel):
    accepted: bool
    accepted_minor: int | None = Field(default=None, ge=1)
    reason: str | None = Field(default=None, max_length=5000)


class CODCollectionOut(BaseModel):
    id: str
    company_id: str
    delivery_assignment_id: str
    order_id: str
    order_number: str
    rider_user_id: str
    rider_name: str | None
    expected_minor: int
    collected_minor: int
    accepted_minor: int | None
    currency: str
    receipt_reference: str
    proof_reference: str
    status: str
    payment_id: str | None
    reconciled_by_id: str | None
    reconciled_at: datetime | None
    reconciliation_reason: str | None
    metadata: dict[str, Any]
    created_at: datetime
    updated_at: datetime


class RiderFinanceProfileUpdate(BaseModel):
    delivery_fee_minor: int = Field(ge=0)
    currency: str = Field(default="PKR", min_length=3, max_length=3)
    is_active: bool = True
    metadata: dict[str, Any] = Field(default_factory=dict)


class RiderFinanceProfileOut(BaseModel):
    id: str
    company_id: str
    rider_user_id: str
    delivery_fee_minor: int
    currency: str
    is_active: bool
    metadata: dict[str, Any]
    created_at: datetime
    updated_at: datetime


class RiderRemittanceCreate(BaseModel):
    amount_minor: int = Field(ge=1)
    reference: str = Field(min_length=2, max_length=160)
    proof_reference: str = Field(min_length=2, max_length=1000)
    idempotency_key: str = Field(min_length=3, max_length=255)
    metadata: dict[str, Any] = Field(default_factory=dict)


class RiderRemittanceReconciliationRequest(BaseModel):
    accepted: bool
    reason: str | None = Field(default=None, max_length=5000)


class RiderCashRemittanceOut(BaseModel):
    id: str
    company_id: str
    rider_user_id: str
    rider_name: str | None
    amount_minor: int
    currency: str
    reference: str
    proof_reference: str
    status: str
    reconciled_by_id: str | None
    reconciled_at: datetime | None
    reconciliation_reason: str | None
    journal_id: str | None
    metadata: dict[str, Any]
    created_at: datetime
    updated_at: datetime


class RiderAdjustmentCreate(BaseModel):
    amount_minor: int
    memo: str = Field(min_length=2, max_length=5000)
    idempotency_key: str = Field(min_length=3, max_length=255)

    @field_validator("amount_minor")
    @classmethod
    def amount_must_not_be_zero(cls, value: int) -> int:
        if value == 0:
            raise ValueError("amount_minor must not be zero")
        return value


class RiderPayoutCreate(BaseModel):
    amount_minor: int = Field(ge=1)
    payment_reference: str = Field(min_length=2, max_length=160)
    idempotency_key: str = Field(min_length=3, max_length=255)
    metadata: dict[str, Any] = Field(default_factory=dict)


class RiderLedgerEntryOut(BaseModel):
    id: str
    company_id: str
    rider_user_id: str
    entry_type: str
    source_type: str
    source_id: str
    amount_minor: int
    balance_minor: int
    currency: str
    memo: str | None
    journal_id: str | None
    metadata: dict[str, Any]
    created_at: datetime
    updated_at: datetime


class RiderPayoutOut(BaseModel):
    id: str
    company_id: str
    rider_user_id: str
    payout_number: str
    amount_minor: int
    currency: str
    payment_reference: str
    status: str
    paid_at: datetime
    paid_by_id: str | None
    journal_id: str | None
    metadata: dict[str, Any]
    created_at: datetime
    updated_at: datetime


class VendorFinanceDecision(BaseModel):
    approved: bool
    reason: str | None = Field(default=None, max_length=5000)


class FinanceDashboardOut(BaseModel):
    collected_sales_minor: int = 0
    pending_cod_minor: int = 0
    rider_cash_in_hand_minor: int = 0
    vendor_payables_minor: int = 0
    approved_vendor_payouts_minor: int = 0
    rider_earnings_payable_minor: int = 0
    delivery_expense_minor: int = 0
    expenses_minor: int = 0
    refunds_minor: int = 0
    net_operational_profit_minor: int = 0
    reconciliation_warnings: int = 0


class SupportContactCreate(BaseModel):
    label: str = Field(min_length=2, max_length=120)
    role: str = Field(default="support", min_length=2, max_length=80)
    phone: str = Field(min_length=5, max_length=80)
    whatsapp_message: str | None = Field(default=None, max_length=1000)
    working_hours: str | None = Field(default=None, max_length=255)
    priority: int = Field(default=0, ge=0, le=999)
    is_active: bool = True


class SupportContactOut(BaseModel):
    id: str
    label: str
    role: str
    phone: str
    whatsapp_url: str
    whatsapp_message: str | None
    working_hours: str | None
    priority: int
    is_active: bool
    created_at: datetime
    updated_at: datetime


class VendorCreate(BaseModel):
    name: str = Field(min_length=2, max_length=255)
    slug: str | None = Field(default=None, min_length=2, max_length=160)
    legal_name: str | None = Field(default=None, max_length=255)
    contact_name: str | None = Field(default=None, max_length=255)
    email: str | None = Field(default=None, max_length=255)
    phone: str | None = Field(default=None, max_length=80)
    status: str = Field(default="pending", min_length=3, max_length=40)
    default_commission_bps: int = Field(default=0, ge=0, le=10000)
    metadata: dict[str, Any] = Field(default_factory=dict)


class VendorUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=255)
    slug: str | None = Field(default=None, min_length=2, max_length=160)
    legal_name: str | None = Field(default=None, max_length=255)
    contact_name: str | None = Field(default=None, max_length=255)
    email: str | None = Field(default=None, max_length=255)
    phone: str | None = Field(default=None, max_length=80)
    status: str | None = Field(default=None, min_length=3, max_length=40)
    default_commission_bps: int | None = Field(default=None, ge=0, le=10000)
    metadata: dict[str, Any] | None = None


class VendorProfileOut(BaseModel):
    id: str
    company_id: str
    name: str
    slug: str
    legal_name: str | None
    contact_name: str | None
    email: str | None
    phone: str | None
    status: str
    default_commission_bps: int
    metadata: dict[str, Any]
    created_at: datetime
    updated_at: datetime


class AdminUserDetailOut(UserOut):
    vendor_profile: VendorProfileOut | None = None


class PendingRegistrationOut(AdminUserDetailOut):
    registration_type: Literal["staff", "vendor"]


class AdminUserUpdate(UserUpdate):
    vendor_profile: VendorUpdate | None = None


class VendorOut(BaseModel):
    id: str
    company_id: str
    name: str
    slug: str
    legal_name: str | None
    contact_name: str | None
    email: str | None
    phone: str | None
    status: str
    access_status: Literal["active", "pending", "paused", "stopped"]
    default_commission_bps: int
    metadata: dict[str, Any]
    created_at: datetime
    updated_at: datetime


class VendorUserCreate(BaseModel):
    user_id: str = Field(min_length=1, max_length=36)
    role_name: str = Field(default="vendor", min_length=2, max_length=80)
    is_primary: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)


class VendorUserOut(BaseModel):
    id: str
    company_id: str
    vendor_id: str
    user_id: str
    role_name: str
    is_primary: bool
    metadata: dict[str, Any]
    created_at: datetime
    updated_at: datetime


class VendorProductAssignRequest(BaseModel):
    vendor_id: str | None = Field(default=None, max_length=36)
    product_id: str = Field(min_length=1, max_length=36)
    approval_status: str = Field(default="submitted", min_length=3, max_length=40)
    ownership_type: Literal["company_owned", "vendor_owned", "consignment"] = "company_owned"
    metadata: dict[str, Any] = Field(default_factory=dict)


class VendorProductOut(BaseModel):
    id: str
    company_id: str
    vendor_id: str
    product_id: str
    ownership_type: str = "company_owned"
    approval_status: str
    approved_by_id: str | None
    approved_at: datetime | None
    rejected_reason: str | None
    published_at: datetime | None
    metadata: dict[str, Any]
    created_at: datetime
    updated_at: datetime


class VendorOrderItemOut(BaseModel):
    id: str
    company_id: str
    vendor_id: str
    order_id: str
    order_item_id: str
    product_id: str
    variant_id: str | None
    sku: str | None
    name: str
    quantity: int
    unit_price_minor: int
    line_total_minor: int
    commission_bps: int
    commission_minor: int
    payable_minor: int
    status: str
    finance_status: str
    finance_approved_by_id: str | None
    finance_approved_at: datetime | None
    finance_reason: str | None
    order_number: str | None = None
    order_status: str | None = None
    payment_status: str | None = None
    settlement_id: str | None
    metadata: dict[str, Any]
    created_at: datetime
    updated_at: datetime


class VendorOrderItemStatusChange(BaseModel):
    status: Literal["accepted", "packing", "dispatched", "delivered", "rejected"]
    reason: str | None = Field(default=None, max_length=5000)


class VendorOrderItemStatusHistoryOut(BaseModel):
    id: str
    vendor_order_item_id: str
    vendor_id: str
    from_status: str | None
    to_status: str
    changed_by_id: str | None
    reason: str | None
    created_at: datetime


class VendorSettlementCreate(BaseModel):
    vendor_id: str | None = Field(default=None, max_length=36)
    settlement_number: str | None = Field(default=None, max_length=80)
    currency: str = Field(default="PKR", min_length=3, max_length=3)
    period_start_at: datetime | None = None
    period_end_at: datetime | None = None
    payment_reference: str | None = Field(default=None, max_length=160)
    metadata: dict[str, Any] = Field(default_factory=dict)


class VendorSettlementOut(BaseModel):
    id: str
    company_id: str
    vendor_id: str
    settlement_number: str
    currency: str
    period_start_at: datetime | None
    period_end_at: datetime | None
    status: str
    gross_minor: int
    commission_minor: int
    payable_minor: int
    paid_minor: int
    payment_reference: str | None
    journal_entry_id: str | None
    paid_at: datetime | None
    metadata: dict[str, Any]
    created_at: datetime
    updated_at: datetime


class CommissionRuleCreate(BaseModel):
    name: str = Field(min_length=2, max_length=255)
    vendor_id: str | None = Field(default=None, max_length=36)
    category_id: str | None = Field(default=None, max_length=36)
    product_id: str | None = Field(default=None, max_length=36)
    commission_bps: int = Field(default=0, ge=0, le=10000)
    is_active: bool = True
    metadata: dict[str, Any] = Field(default_factory=dict)


class CommissionRuleUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=255)
    vendor_id: str | None = Field(default=None, max_length=36)
    category_id: str | None = Field(default=None, max_length=36)
    product_id: str | None = Field(default=None, max_length=36)
    commission_bps: int | None = Field(default=None, ge=0, le=10000)
    is_active: bool | None = None
    metadata: dict[str, Any] | None = None


class CommissionRuleOut(BaseModel):
    id: str
    company_id: str
    name: str
    vendor_id: str | None
    category_id: str | None
    product_id: str | None
    commission_bps: int
    is_active: bool
    metadata: dict[str, Any]
    created_at: datetime
    updated_at: datetime


class VendorLedgerEntryOut(BaseModel):
    id: str
    company_id: str
    vendor_id: str
    entry_type: str
    source_type: str | None
    source_id: str | None
    amount_minor: int
    balance_minor: int
    memo: str | None
    metadata: dict[str, Any]
    created_at: datetime
    updated_at: datetime


class VendorNotificationOut(BaseModel):
    id: str
    company_id: str
    vendor_id: str
    channel: str
    notification_type: str
    subject: str | None
    body: str
    status: str
    metadata: dict[str, Any]
    created_at: datetime
    updated_at: datetime


class AccountCreate(BaseModel):
    code: str = Field(min_length=1, max_length=40)
    name: str = Field(min_length=2, max_length=255)
    account_type: str = Field(min_length=2, max_length=40)
    parent_id: str | None = Field(default=None, max_length=36)
    is_active: bool = True
    metadata: dict[str, Any] = Field(default_factory=dict)


class AccountUpdate(BaseModel):
    code: str | None = Field(default=None, min_length=1, max_length=40)
    name: str | None = Field(default=None, min_length=2, max_length=255)
    account_type: str | None = Field(default=None, min_length=2, max_length=40)
    parent_id: str | None = Field(default=None, max_length=36)
    is_active: bool | None = None
    metadata: dict[str, Any] | None = None


class AccountOut(BaseModel):
    id: str
    company_id: str
    code: str
    name: str
    account_type: str
    parent_id: str | None
    is_active: bool
    metadata: dict[str, Any]
    created_at: datetime
    updated_at: datetime


class AccountingPeriodCreate(BaseModel):
    name: str = Field(min_length=2, max_length=255)
    starts_at: datetime
    ends_at: datetime
    status: str = Field(default="open", min_length=3, max_length=40)
    metadata: dict[str, Any] = Field(default_factory=dict)


class AccountingPeriodUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=255)
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    status: str | None = Field(default=None, min_length=3, max_length=40)
    locked_at: datetime | None = None
    metadata: dict[str, Any] | None = None


class AccountingPeriodOut(BaseModel):
    id: str
    company_id: str
    name: str
    starts_at: datetime
    ends_at: datetime
    status: str
    locked_at: datetime | None
    metadata: dict[str, Any]
    created_at: datetime
    updated_at: datetime


class JournalLineCreate(BaseModel):
    account_id: str = Field(min_length=1, max_length=36)
    debit_minor: int = Field(default=0, ge=0)
    credit_minor: int = Field(default=0, ge=0)
    memo: str | None = Field(default=None, max_length=5000)
    metadata: dict[str, Any] = Field(default_factory=dict)


class JournalLineOut(BaseModel):
    id: str
    company_id: str
    journal_entry_id: str
    account_id: str
    debit_minor: int
    credit_minor: int
    memo: str | None
    metadata: dict[str, Any]


class JournalEntryCreate(BaseModel):
    entry_number: str | None = Field(default=None, max_length=80)
    source_type: str | None = Field(default=None, max_length=80)
    source_id: str | None = Field(default=None, max_length=120)
    memo: str | None = Field(default=None, max_length=5000)
    posted_at: datetime | None = None
    status: str = Field(default="posted", min_length=3, max_length=40)
    metadata: dict[str, Any] = Field(default_factory=dict)
    lines: list[JournalLineCreate] = Field(min_length=2, max_length=100)


class JournalEntryOut(BaseModel):
    id: str
    company_id: str
    entry_number: str
    source_type: str | None
    source_id: str | None
    memo: str | None
    status: str
    posted_at: datetime | None
    metadata: dict[str, Any]
    lines: list[JournalLineOut]
    created_at: datetime
    updated_at: datetime


class CashBookCreate(BaseModel):
    code: str = Field(min_length=1, max_length=40)
    name: str = Field(min_length=2, max_length=255)
    currency: str = Field(default="PKR", min_length=3, max_length=3)
    opening_balance_minor: int = Field(default=0)
    is_active: bool = True
    metadata: dict[str, Any] = Field(default_factory=dict)


class CashBookOut(BaseModel):
    id: str
    company_id: str
    code: str
    name: str
    currency: str
    opening_balance_minor: int
    is_active: bool
    metadata: dict[str, Any]
    created_at: datetime
    updated_at: datetime


class BankAccountCreate(BaseModel):
    code: str = Field(min_length=1, max_length=40)
    bank_name: str = Field(min_length=2, max_length=255)
    account_name: str = Field(min_length=2, max_length=255)
    account_number: str | None = Field(default=None, max_length=120)
    iban: str | None = Field(default=None, max_length=80)
    currency: str = Field(default="PKR", min_length=3, max_length=3)
    opening_balance_minor: int = Field(default=0)
    is_active: bool = True
    metadata: dict[str, Any] = Field(default_factory=dict)


class BankAccountOut(BaseModel):
    id: str
    company_id: str
    code: str
    bank_name: str
    account_name: str
    account_number: str | None
    iban: str | None
    currency: str
    opening_balance_minor: int
    is_active: bool
    metadata: dict[str, Any]
    created_at: datetime
    updated_at: datetime


class ExpenseCreate(BaseModel):
    expense_number: str | None = Field(default=None, max_length=80)
    account_id: str = Field(min_length=1, max_length=36)
    vendor_id: str | None = Field(default=None, max_length=36)
    cash_book_id: str | None = Field(default=None, max_length=36)
    bank_account_id: str | None = Field(default=None, max_length=36)
    amount_minor: int = Field(ge=1)
    currency: str = Field(default="PKR", min_length=3, max_length=3)
    status: str = Field(default="draft", min_length=3, max_length=40)
    memo: str | None = Field(default=None, max_length=5000)
    incurred_at: datetime | None = None
    paid_at: datetime | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ExpenseOut(BaseModel):
    id: str
    company_id: str
    expense_number: str
    account_id: str
    vendor_id: str | None
    cash_book_id: str | None
    bank_account_id: str | None
    amount_minor: int
    currency: str
    status: str
    memo: str | None
    incurred_at: datetime | None
    paid_at: datetime | None
    metadata: dict[str, Any]
    created_at: datetime
    updated_at: datetime


class WooCommerceConfigRequest(BaseModel):
    site_url: str = Field(min_length=8, max_length=2000)
    consumer_key: str = Field(min_length=8, max_length=255)
    consumer_secret: str = Field(min_length=8, max_length=255)
    webhook_secret: str | None = Field(default=None, min_length=8, max_length=255)
    wordpress_username: str | None = Field(default=None, min_length=1, max_length=255)
    wordpress_application_password: str | None = Field(default=None, min_length=8, max_length=255)


class WooCommerceConfigOut(BaseModel):
    configured: bool
    site_url: str | None
    consumer_key_hint: str | None
    wordpress_username: str | None = None
    wordpress_media_configured: bool = False
    webhook_secret_configured: bool = False
    pending_product_pushes: int = 0
    pending_media_pushes: int = 0
    pending_video_pushes: int = 0
    failed_product_pushes: int = 0
    failed_media_pushes: int = 0
    failed_video_pushes: int = 0
    last_media_error: str | None = None
    last_video_error: str | None = None
    video_plugin_detected: bool = False
    video_plugin_compatible: bool = False
    video_plugin_version: str | None = None
    wordpress_max_upload_bytes: int | None = None
    queued_sync_runs: int = 0
    running_sync_runs: int = 0
    active_sync_run_id: str | None = None
    active_sync_worker_id: str | None = None
    updated_at: datetime | None


class WooCommerceConnectionTestOut(BaseModel):
    ok: bool
    status: str
    detail: str
    video_plugin_detected: bool = False
    video_plugin_compatible: bool = False
    video_plugin_version: str | None = None
    wordpress_max_upload_bytes: int | None = None


class WhatsAppTemplateCreate(BaseModel):
    name: str = Field(min_length=2, max_length=120, pattern=r"^[A-Za-z0-9_.-]+$")
    language: str = Field(default="en", min_length=2, max_length=12)
    body: str = Field(min_length=1, max_length=5000)


class WhatsAppTemplateOut(BaseModel):
    id: str
    company_id: str
    name: str
    language: str
    body: str
    is_active: bool
    created_at: datetime
    updated_at: datetime


class WhatsAppMessageEnqueue(BaseModel):
    recipient_phone: str = Field(min_length=8, max_length=80)
    template_id: str | None = Field(default=None, max_length=36)
    body: str | None = Field(default=None, min_length=1, max_length=5000)
    variables: dict[str, Any] = Field(default_factory=dict)
    idempotency_key: str | None = Field(default=None, max_length=180)
    metadata: dict[str, Any] = Field(default_factory=dict)
    scheduled_at: datetime | None = None


class WhatsAppMessageOut(BaseModel):
    id: str
    company_id: str
    template_id: str | None
    recipient_phone: str
    message_body: str
    status: str
    idempotency_key: str | None
    metadata: dict[str, Any]
    scheduled_at: datetime | None
    sent_at: datetime | None
    failed_at: datetime | None
    last_error: str | None
    created_at: datetime
    updated_at: datetime


class WhatsAppMockSendRequest(BaseModel):
    force_failure: bool = False


class WhatsAppDeliveryLogOut(BaseModel):
    id: str
    notification_id: str
    status: str
    adapter: str
    provider_message_id: str | None
    error: str | None
    payload: dict[str, Any]
    created_at: datetime


class DashboardSummaryOut(BaseModel):
    sales_count: int
    revenue_minor: int
    pending_orders: int
    low_stock_count: int
    customer_count: int
    product_count: int


class SalesReportRow(BaseModel):
    status: str
    order_count: int
    revenue_minor: int


class InventoryReportRow(BaseModel):
    product_id: str
    variant_id: str | None
    warehouse_id: str | None
    quantity_on_hand: int


class CustomerReportRow(BaseModel):
    id: str
    full_name: str
    phone: str | None
    email: str | None
    status: str


class OrderReportRow(BaseModel):
    id: str
    order_number: str
    customer_id: str
    status: str
    total_minor: int
    paid_minor: int
    payment_status: str
    created_at: datetime


class BackupMetadataOut(BaseModel):
    backup_id: str
    database_url_driver: str
    source_path: str
    backup_path: str
    metadata_path: str
    size_bytes: int
    created_at: datetime


class RestorePlanRequest(BaseModel):
    backup_path: str = Field(min_length=1, max_length=2000)


class RestorePlanOut(BaseModel):
    safe_to_restore: bool
    backup_path: str
    size_bytes: int | None
    strategy: str
    requires_confirmation: bool
    detail: str


class LicenseActivationRequest(BaseModel):
    license_key: str = Field(min_length=8, max_length=255)
    plan: str = Field(default="standard", min_length=2, max_length=80)


class LicenseStatusOut(BaseModel):
    configured: bool
    status: str
    plan: str | None
    activated_at: datetime | None
    expires_at: datetime | None
    grace_expires_at: datetime | None
    license_id: str | None = None
    device_id: str | None = None
    activation_mode: str | None = None
    last_validated_at: datetime | None = None


class LicenseValidationOut(BaseModel):
    configured: bool
    status: str
    detail: str
    validated_at: datetime


class LicenseRevokeRequest(BaseModel):
    reason: str | None = Field(default=None, max_length=5000)


class LicenseServerActivationRequest(BaseModel):
    license_key: str = Field(min_length=8, max_length=255)
    company_id: str = Field(min_length=1, max_length=80)
    company_name: str = Field(min_length=2, max_length=255)
    device_id: str = Field(min_length=2, max_length=160)
    plan: str = Field(default="standard", min_length=2, max_length=80)


class LicenseServerValidationRequest(BaseModel):
    license_id: str | None = Field(default=None, max_length=80)
    license_key_hash: str | None = Field(default=None, max_length=128)
    device_id: str = Field(min_length=2, max_length=160)


class LicenseServerMutationRequest(BaseModel):
    license_id: str | None = Field(default=None, max_length=80)
    license_key: str | None = Field(default=None, min_length=8, max_length=255)
    reason: str | None = Field(default=None, max_length=5000)
    extend_days: int = Field(default=365, ge=1, le=3650)


class LicenseServerResponse(BaseModel):
    license_id: str
    license_key_hash: str
    status: str
    plan: str
    device_id: str
    activated_at: datetime | None
    expires_at: datetime | None
    grace_expires_at: datetime | None
    signed_payload: str
    signature: str


class DiagnosticsSummaryOut(BaseModel):
    app_version: str
    environment: str
    database_driver: str
    migration_revision: str | None
    expected_migration_revision: str | None = None
    database_ready: bool = False
    company_id: str | None
    module_count: int
    settings: dict[str, object]
    runtime: dict[str, object] = Field(default_factory=dict)
    generated_at: datetime


class SyncRunLogOut(BaseModel):
    id: str
    company_id: str | None
    connector: str
    direction: str
    started_at: datetime
    finished_at: datetime | None = None
    status: str
    stats: dict[str, Any]
    error: str | None = None
    attempts: int = 0
    worker_id: str | None = None
    lease_expires_at: datetime | None = None


class SyncConflictOut(BaseModel):
    id: str
    company_id: str | None
    connector: str
    resource_type: str
    resource_id: str | None
    external_resource_id: str | None
    conflict_type: str
    local_payload: dict[str, Any]
    remote_payload: dict[str, Any]
    status: str
    resolution: str | None
    created_at: datetime
    updated_at: datetime


class SyncConflictResolveRequest(BaseModel):
    resolution: str
    strategy: str = Field(min_length=3, max_length=40)


# Production authentication, vendor onboarding, ledger, and inventory contracts.

AccountStatus = Literal["active", "pending", "paused", "stopped"]
VendorStatusInput = Literal[
    "active",
    "pending",
    "paused",
    "stopped",
    "approved",
    "suspended",
    "rejected",
]
OwnershipType = Literal["company_owned", "vendor_owned", "consignment"]


class StatusChangeRequest(BaseModel):
    status: VendorStatusInput
    reason: str | None = Field(default=None, max_length=2000)


class VendorLifecycleRequest(BaseModel):
    reason: str | None = Field(default=None, max_length=2000)


class AdminVendorAccountCreate(BaseModel):
    business_name: str = Field(min_length=2, max_length=255)
    username: str = Field(min_length=3, max_length=120, pattern=r"^[A-Za-z0-9_.-]+$")
    email: str | None = Field(default=None, max_length=255)
    contact_name: str | None = Field(default=None, max_length=255)
    phone: str | None = Field(default=None, max_length=80)
    password: str | None = Field(default=None, min_length=8, max_length=128)
    use_activation: bool = True
    default_commission_bps: int = Field(default=0, ge=0, le=10000)


class AdminVendorAccountOut(BaseModel):
    vendor: VendorOut
    user: UserOut
    # Kept for wire compatibility. Raw activation credentials are never returned.
    activation_token: str | None = None
    activation_expires_at: datetime | None = None
    onboarding_method: Literal["activation", "temporary_password"]
    activation_delivery: Literal["sent", "not_requested"]


class LedgerAccountCreate(BaseModel):
    code: str = Field(min_length=1, max_length=40)
    name: str = Field(min_length=2, max_length=255)
    account_type: Literal["asset", "liability", "equity", "income", "expense", "contra"]
    parent_id: str | None = Field(default=None, max_length=36)
    currency: str = Field(default="PKR", min_length=3, max_length=3)
    metadata: dict[str, Any] = Field(default_factory=dict)


class LedgerAccountOut(BaseModel):
    id: str
    company_id: str
    code: str
    name: str
    account_type: str
    parent_id: str | None
    is_active: bool
    currency: str
    metadata: dict[str, Any]
    created_at: datetime
    updated_at: datetime


class LedgerPeriodCreate(BaseModel):
    name: str = Field(min_length=2, max_length=255)
    starts_at: datetime
    ends_at: datetime


class LedgerPeriodStatusRequest(BaseModel):
    status: Literal["open", "locked", "closed"]
    reason: str = Field(min_length=2, max_length=2000)


class LedgerPeriodOut(BaseModel):
    id: str
    company_id: str
    name: str
    starts_at: datetime
    ends_at: datetime
    status: str
    locked_at: datetime | None
    closed_at: datetime | None
    closed_by_id: str | None
    created_at: datetime
    updated_at: datetime


class LedgerLineCreate(BaseModel):
    account_id: str = Field(min_length=1, max_length=36)
    vendor_id: str | None = Field(default=None, max_length=36)
    debit_minor: int = Field(default=0, ge=0)
    credit_minor: int = Field(default=0, ge=0)
    currency: str = Field(default="PKR", min_length=3, max_length=3)
    memo: str | None = Field(default=None, max_length=5000)
    metadata: dict[str, Any] = Field(default_factory=dict)


class LedgerJournalCreate(BaseModel):
    source_type: str = Field(default="manual_adjustment", min_length=2, max_length=80)
    source_id: str | None = Field(default=None, max_length=120)
    idempotency_key: str | None = Field(default=None, max_length=255)
    memo: str = Field(min_length=2, max_length=5000)
    posted_at: datetime | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    lines: list[LedgerLineCreate] = Field(min_length=2, max_length=200)


class LedgerLineOut(BaseModel):
    id: str
    journal_id: str
    company_id: str
    account_id: str
    vendor_id: str | None
    debit_minor: int
    credit_minor: int
    currency: str
    memo: str | None
    metadata: dict[str, Any]


class LedgerJournalOut(BaseModel):
    id: str
    company_id: str
    entry_number: str
    source_type: str
    source_id: str
    idempotency_key: str
    status: str
    posted_at: datetime | None
    created_by_id: str | None
    reversal_of_id: str | None
    memo: str | None
    metadata: dict[str, Any]
    lines: list[LedgerLineOut]
    created_at: datetime
    updated_at: datetime


class LedgerReverseRequest(BaseModel):
    reason: str = Field(min_length=2, max_length=5000)
    idempotency_key: str | None = Field(default=None, max_length=255)


class TrialBalanceRow(BaseModel):
    account_id: str
    account_code: str
    account_name: str
    account_type: str
    debit_minor: int
    credit_minor: int
    balance_minor: int


class LedgerOverviewOut(BaseModel):
    assets_minor: int = 0
    liabilities_minor: int = 0
    equity_minor: int = 0
    income_minor: int = 0
    expenses_minor: int = 0
    vendor_payables_minor: int = 0
    inventory_on_hand: int = 0
    inventory_reserved: int = 0
    inventory_value_minor: int = 0
    cash_balance_minor: int = 0
    vendor_count: int = 0
    order_count: int = 0
    gross_order_minor: int = 0
    paid_sales_minor: int = 0
    commission_minor: int = 0
    settlement_count: int = 0
    settlement_payable_minor: int = 0
    settlement_paid_minor: int = 0
    journal_count: int = 0
    reconciliation_warnings: int = 0


class VendorInventoryMovementCreate(BaseModel):
    vendor_id: str = Field(min_length=1, max_length=36)
    product_id: str = Field(min_length=1, max_length=36)
    variant_id: str | None = Field(default=None, max_length=36)
    warehouse_id: str = Field(min_length=1, max_length=36)
    movement_type: Literal[
        "opening_balance",
        "receipt",
        "sale",
        "reservation",
        "reservation_release",
        "return",
        "adjustment",
        "damage",
        "transfer_in",
        "transfer_out",
        "stock_count_correction",
    ]
    quantity_delta: int = 0
    reserved_quantity_delta: int = 0
    ownership_type: OwnershipType
    unit_cost_minor: int | None = Field(default=None, ge=0)
    currency: str = Field(default="PKR", min_length=3, max_length=3)
    source_type: str = Field(min_length=2, max_length=80)
    source_id: str = Field(min_length=1, max_length=120)
    idempotency_key: str = Field(min_length=3, max_length=255)
    transfer_group_id: str | None = Field(default=None, max_length=36)
    occurred_at: datetime | None = None
    reason: str = Field(min_length=2, max_length=5000)
    metadata: dict[str, Any] = Field(default_factory=dict)


class VendorInventoryBalanceOut(BaseModel):
    id: str
    company_id: str
    vendor_id: str
    product_id: str
    variant_id: str | None
    warehouse_id: str
    ownership_type: str
    on_hand_quantity: int
    reserved_quantity: int
    available_quantity: int
    unit_cost_minor: int | None
    currency: str
    last_movement_at: datetime | None


class VendorInventoryMovementOut(BaseModel):
    id: str
    company_id: str
    vendor_id: str
    product_id: str
    variant_id: str | None
    warehouse_id: str
    movement_type: str
    quantity_delta: int
    quantity_before: int
    quantity_after: int
    reserved_quantity_delta: int
    ownership_type: str
    unit_cost_minor: int | None
    valuation_minor: int | None
    currency: str
    source_type: str
    source_id: str
    transfer_group_id: str | None
    occurred_at: datetime
    reason: str | None
    metadata: dict[str, Any]
    created_at: datetime


class VendorLedgerOverviewOut(BaseModel):
    vendor_id: str
    vendor_status: str
    gross_sales_minor: int = 0
    commission_minor: int = 0
    payable_minor: int = 0
    settled_minor: int = 0
    outstanding_minor: int = 0
    order_count: int = 0
    settlement_count: int = 0
    stock_on_hand: int = 0
    stock_reserved: int = 0
    stock_available: int = 0


class VendorLedgerLineOut(BaseModel):
    journal_id: str
    entry_number: str
    source_type: str
    source_id: str
    posted_at: datetime | None
    memo: str | None
    debit_minor: int
    credit_minor: int
    balance_minor: int
    currency: str


class ReconciliationIssueOut(BaseModel):
    issue_type: str
    severity: Literal["warning", "error"]
    source_id: str | None = None
    vendor_id: str | None = None
    expected_minor: int | None = None
    actual_minor: int | None = None
    detail: str
