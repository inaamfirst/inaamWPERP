from __future__ import annotations

import base64
import hashlib
import hmac
import json
import mimetypes
import re
import uuid
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, File, Header, HTTPException, Request, Response, UploadFile
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from erp import __version__
from erp.packages.core.admin_services import (
    create_company,
    create_role,
    create_user,
    get_primary_vendor_for_user,
    get_user,
    list_companies,
    list_users,
    reset_user_password,
    update_company,
    update_role,
    update_user_and_vendor,
)
from erp.packages.core.api.dependencies import (
    CurrentContext,
    DbSession,
    OptionalCurrentContext,
    require_any_permission,
    require_permission,
    service_error_to_http,
)
from erp.packages.core.auth_delivery import deliver_action_token
from erp.packages.core.backup_services import (
    BackupMetadata,
    RestorePlan,
    build_restore_plan,
    create_sqlite_backup,
)
from erp.packages.core.catalog_services import (
    archive_brand,
    archive_category,
    archive_product,
    create_brand,
    create_category,
    create_product,
    get_brand,
    get_category,
    get_product,
    list_brands,
    list_categories,
    list_products,
    permanently_delete_product,
    product_category_ids,
    product_images,
    product_relationship_ids,
    product_tag_names,
    product_variants,
    suggest_product_codes,
    update_brand,
    update_category,
    update_product,
)
from erp.packages.core.config import get_settings
from erp.packages.core.customer_services import (
    add_customer_address,
    add_customer_note,
    archive_customer,
    create_customer,
    customer_addresses,
    customer_notes,
    customer_tags,
    get_customer,
    list_customers,
    update_customer,
)
from erp.packages.core.db.models import (
    AuditLog,
    Brand,
    Category,
    Company,
    Customer,
    CustomerAddress,
    CustomerNote,
    NotificationDeliveryLog,
    NotificationQueue,
    NotificationTemplate,
    Order,
    OrderItem,
    OrderStatusHistory,
    Payment,
    Product,
    ProductImage,
    ProductVariant,
    Role,
    Setting,
    StockMovement,
    SyncConflict,
    SyncRunLog,
    User,
    UserRole,
    Warehouse,
)
from erp.packages.core.diagnostics_services import (
    DiagnosticsSummary,
    create_diagnostics_zip,
    current_migration_revision,
    diagnostics_summary,
    expected_migration_revision,
    is_database_migration_current,
)
from erp.packages.core.inventory_services import (
    StockLevel,
    archive_warehouse,
    create_warehouse,
    get_warehouse,
    list_stock_movements,
    list_warehouses,
    record_stock_movement,
    stock_levels,
    update_warehouse,
)
from erp.packages.core.licensing_services import (
    LicenseState,
    LicenseValidation,
    activate_license,
    license_state,
    revoke_license,
    validate_license,
)
from erp.packages.core.marketplace_services import vendor_for_user
from erp.packages.core.modules.manifest import load_module_manifests
from erp.packages.core.order_services import (
    change_order_status,
    create_order,
    get_order,
    list_orders,
    order_items,
    order_payments,
    order_status_history,
    record_payment,
)
from erp.packages.core.report_services import (
    DashboardSummary,
    InventoryReportItem,
    SalesReportItem,
    customer_report,
    dashboard_summary,
    inventory_report,
    order_report,
    orders_csv,
    sales_report,
)
from erp.packages.core.schemas import (
    ActivationConfirm,
    AdminUserDetailOut,
    AdminUserUpdate,
    AuditLogOut,
    AuthResponse,
    BackupMetadataOut,
    BrandCreate,
    BrandOut,
    BrandUpdate,
    CategoryCreate,
    CategoryOut,
    CategoryUpdate,
    CompanyCreate,
    CompanyOut,
    CompanyUpdate,
    CurrentUserResponse,
    CustomerAddressCreate,
    CustomerAddressOut,
    CustomerCreate,
    CustomerNoteCreate,
    CustomerNoteOut,
    CustomerOut,
    CustomerReportRow,
    CustomerUpdate,
    DashboardSummaryOut,
    DiagnosticsSummaryOut,
    FirstUseSetupRequest,
    InventoryReportRow,
    LicenseActivationRequest,
    LicenseRevokeRequest,
    LicenseStatusOut,
    LicenseValidationOut,
    LoginRequest,
    LogoutRequest,
    OrderCreate,
    OrderItemOut,
    OrderOut,
    OrderReportRow,
    OrderStatusChange,
    OrderStatusHistoryOut,
    PasswordChangeRequest,
    PasswordResetConfirm,
    PasswordResetRequest,
    PaymentCreate,
    PaymentOut,
    PermissionOut,
    ProductCodeSuggestionOut,
    ProductCreate,
    ProductImageOut,
    ProductOut,
    ProductUpdate,
    ProductVariantOut,
    RefreshRequest,
    RegistrationResponse,
    RestorePlanOut,
    RestorePlanRequest,
    RoleCreate,
    RoleOut,
    RoleUpdate,
    SalesReportRow,
    SettingOut,
    SettingUpdateRequest,
    SetupStatus,
    StockLevelOut,
    StockMovementCreate,
    StockMovementOut,
    SyncConflictOut,
    SyncConflictResolveRequest,
    SyncRunLogOut,
    UserCreate,
    UserOut,
    UserPasswordReset,
    UserUpdate,
    VendorProfileOut,
    VendorRegistrationRequest,
    WarehouseCreate,
    WarehouseOut,
    WarehouseUpdate,
    WhatsAppDeliveryLogOut,
    WhatsAppMessageEnqueue,
    WhatsAppMessageOut,
    WhatsAppMockSendRequest,
    WhatsAppTemplateCreate,
    WhatsAppTemplateOut,
    WooCommerceConfigOut,
    WooCommerceConfigRequest,
    WooCommerceConnectionTestOut,
)
from erp.packages.core.security import hash_session_token
from erp.packages.core.services import (
    AuthContext,
    IssuedSession,
    ServiceError,
    auth_throttle_scope_keys,
    authenticate,
    change_password,
    check_auth_throttle,
    confirm_activation,
    confirm_password_reset,
    create_action_token,
    declared_permissions,
    is_configured,
    list_audit_logs,
    list_roles,
    list_settings,
    record_auth_throttle_attempt,
    revoke_refresh_token,
    revoke_session,
    role_permissions,
    rotate_refresh_token,
    setup_first_use,
    upsert_setting,
)
from erp.packages.core.vendor_auth_services import (
    find_password_reset_user,
    register_public_vendor,
)
from erp.packages.core.whatsapp_services import (
    create_template,
    deliver_with_mock_adapter,
    delivery_logs,
    enqueue_message,
    list_messages,
    list_templates,
)
from erp.packages.core.woocommerce_services import (
    configure_woocommerce,
    enqueue_product_sync,
    enqueue_woocommerce_sync_run,
    list_sync_conflicts,
    list_sync_runs,
    load_woocommerce_config,
    process_webhook_event,
    resolve_sync_conflict,
    test_woocommerce_connection,
    woocommerce_sync_job_status,
    woocommerce_sync_outbox_status,
)

router = APIRouter()
SETTING_KEY_PATTERN = re.compile(r"^[A-Za-z0-9_.-]{1,160}$")
PRODUCT_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
PRODUCT_IMAGE_MIME_TYPES = {
    "image/jpeg",
    "image/png",
    "image/webp",
    "image/gif",
}


def _enqueue_product_sync_if_configured(
    db: Session,
    *,
    company_id: str | None,
    product: Product,
) -> None:
    try:
        enqueue_product_sync(db, company_id=company_id, product=product)
    except ServiceError as exc:
        if exc.status_code == 404 and exc.message == "WooCommerce is not configured.":
            return
        raise


def enabled_module_manifests(settings: object) -> list[object]:
    manifests = load_module_manifests()
    whatsapp_enabled = bool(getattr(settings, "effective_whatsapp_enabled", True))
    if whatsapp_enabled:
        return manifests
    return [manifest for manifest in manifests if manifest.id != "whatsapp"]
PRODUCT_IMAGE_MAX_BYTES = 8 * 1024 * 1024
ManageRolesContext = Annotated[
    AuthContext,
    Depends(require_permission("identity.manage_roles")),
]
SettingsViewContext = Annotated[
    AuthContext,
    Depends(require_permission("settings.view")),
]
SettingsManageContext = Annotated[
    AuthContext,
    Depends(require_permission("settings.manage")),
]
AuditViewContext = Annotated[
    AuthContext,
    Depends(require_permission("audit.view")),
]
CatalogViewContext = Annotated[
    AuthContext,
    Depends(require_permission("catalog.view")),
]
CatalogManageContext = Annotated[
    AuthContext,
    Depends(require_permission("catalog.manage")),
]
CustomersViewContext = Annotated[
    AuthContext,
    Depends(require_permission("customers.view")),
]
CustomersManageContext = Annotated[
    AuthContext,
    Depends(require_permission("customers.manage")),
]
InventoryViewContext = Annotated[
    AuthContext,
    Depends(require_permission("inventory.view")),
]
InventoryManageContext = Annotated[
    AuthContext,
    Depends(require_permission("inventory.manage")),
]
OrdersViewContext = Annotated[
    AuthContext,
    Depends(require_permission("orders.view")),
]
OrdersManageContext = Annotated[
    AuthContext,
    Depends(require_permission("orders.manage")),
]
WooCommerceViewContext = Annotated[
    AuthContext,
    Depends(require_permission("woocommerce.view")),
]
WooCommerceConfigureContext = Annotated[
    AuthContext,
    Depends(require_permission("woocommerce.configure")),
]
WooCommerceSyncContext = Annotated[
    AuthContext,
    Depends(require_permission("woocommerce.sync")),
]
DashboardWooCommerceSyncContext = Annotated[
    AuthContext,
    Depends(require_any_permission("woocommerce.sync", "vendor.products.manage")),
]
WhatsAppViewContext = Annotated[
    AuthContext,
    Depends(require_permission("whatsapp.view")),
]
WhatsAppConfigureContext = Annotated[
    AuthContext,
    Depends(require_permission("whatsapp.configure")),
]
WhatsAppSendContext = Annotated[
    AuthContext,
    Depends(require_permission("whatsapp.send")),
]
ReportsViewContext = Annotated[
    AuthContext,
    Depends(require_permission("reports.view")),
]
ReportsExportContext = Annotated[
    AuthContext,
    Depends(require_permission("reports.export")),
]
BackupCreateContext = Annotated[
    AuthContext,
    Depends(require_permission("backup.create")),
]
BackupRestoreContext = Annotated[
    AuthContext,
    Depends(require_permission("backup.restore")),
]
LicensingViewContext = Annotated[
    AuthContext,
    Depends(require_permission("licensing.view")),
]
LicensingManageContext = Annotated[
    AuthContext,
    Depends(require_permission("licensing.manage")),
]
TenancyViewContext = Annotated[
    AuthContext,
    Depends(require_permission("tenancy.view_companies")),
]
TenancyManageContext = Annotated[
    AuthContext,
    Depends(require_permission("tenancy.manage_companies")),
]
UsersViewContext = Annotated[
    AuthContext,
    Depends(require_permission("identity.view_users")),
]
UsersManageContext = Annotated[
    AuthContext,
    Depends(require_permission("identity.manage_users")),
]
SupportViewContext = Annotated[
    AuthContext,
    Depends(require_permission("support.view_diagnostics")),
]


@router.get("/health", tags=["system"])
def health(request: Request, db: DbSession) -> dict[str, object]:
    settings = getattr(request.app.state, "settings", get_settings())
    modules = enabled_module_manifests(settings)
    current_revision = current_migration_revision(db)
    expected_revision = expected_migration_revision()
    database_ready = is_database_migration_current(db)
    return {
        "app_name": settings.app_name,
        "version": __version__,
        "status": "healthy" if database_ready else "degraded",
        "environment": settings.env,
        "database_configured": settings.database_configured,
        "database_ready": database_ready,
        "migration_revision": current_revision,
        "expected_migration_revision": expected_revision,
        "module_count": len(modules),
    }


@router.get("/modules", tags=["system"])
def modules(request: Request) -> dict[str, object]:
    settings = getattr(request.app.state, "settings", get_settings())
    manifests = enabled_module_manifests(settings)
    return {
        "modules": [manifest.summary() for manifest in manifests],
        "count": len(manifests),
    }


def company_out(company: Company | None) -> CompanyOut | None:
    if company is None:
        return None
    return CompanyOut(
        id=company.id,
        name=company.name,
        slug=company.slug,
        legal_name=company.legal_name,
        status=company.status,
        created_at=company.created_at,
        updated_at=company.updated_at,
    )


def user_out(user: User, db: Session | None = None) -> UserOut:
    role_rows = (
        list(
            db.execute(
                select(Role.id, Role.name)
                .join(UserRole, UserRole.role_id == Role.id)
                .where(UserRole.user_id == user.id, Role.company_id == user.company_id)
                .order_by(Role.name, Role.id)
            ).all()
        )
        if db is not None
        else []
    )

    return UserOut(
        id=user.id,
        company_id=user.company_id,
        username=user.username,
        email=user.email,
        full_name=user.full_name,
        is_active=user.is_active,
        account_status=user.account_status,
        must_change_password=user.must_change_password,
        password_changed_at=user.password_changed_at,
        last_login_at=user.last_login_at,
        role_ids=[str(role_id) for role_id, _role_name in role_rows],
        role_names=[str(role_name) for _role_id, role_name in role_rows],
        created_at=user.created_at,
        updated_at=user.updated_at,
    )


def admin_user_detail_out(user: User, db: Session) -> AdminUserDetailOut:
    base = user_out(user, db)
    vendor = get_primary_vendor_for_user(db, user.company_id, user.id)
    vendor_profile = (
        VendorProfileOut(
            id=vendor.id,
            company_id=vendor.company_id,
            name=vendor.name,
            slug=vendor.slug,
            legal_name=vendor.legal_name,
            contact_name=vendor.contact_name,
            email=vendor.email,
            phone=vendor.phone,
            status=vendor.status,
            default_commission_bps=vendor.default_commission_bps,
            metadata=vendor.metadata_json,
            created_at=vendor.created_at,
            updated_at=vendor.updated_at,
        )
        if vendor is not None
        else None
    )
    return AdminUserDetailOut(**base.model_dump(), vendor_profile=vendor_profile)


def auth_response(issued: IssuedSession) -> AuthResponse:
    return AuthResponse(
        access_token=issued.token,
        expires_at=issued.session.expires_at,
        refresh_token=issued.refresh_token,
        refresh_expires_at=issued.refresh_expires_at,
        session_id=issued.session.id,
        user=user_out(issued.user),
        company=company_out(issued.company),
        permissions=issued.permissions,
    )


def role_out(db: Session, role: Role) -> RoleOut:
    return RoleOut(
        id=role.id,
        company_id=role.company_id,
        name=role.name,
        description=role.description,
        permissions=role_permissions(db, role.id),
    )


def setting_out(setting: Setting) -> SettingOut:
    return SettingOut(key=setting.key, value=setting.value, updated_at=setting.updated_at)


def audit_log_out(entry: AuditLog) -> AuditLogOut:
    return AuditLogOut(
        id=entry.id,
        company_id=entry.company_id,
        user_id=entry.user_id,
        action=entry.action,
        entity_type=entry.entity_type,
        entity_id=entry.entity_id,
        metadata=entry.metadata_json,
        created_at=entry.created_at,
    )


def category_out(category: Category) -> CategoryOut:
    return CategoryOut(
        id=category.id,
        company_id=category.company_id,
        parent_id=category.parent_id,
        name=category.name,
        slug=category.slug,
        description=category.description,
        is_active=category.is_active,
        created_at=category.created_at,
        updated_at=category.updated_at,
    )


def brand_out(brand: Brand) -> BrandOut:
    return BrandOut(
        id=brand.id,
        company_id=brand.company_id,
        name=brand.name,
        slug=brand.slug,
        description=brand.description,
        is_active=brand.is_active,
        created_at=brand.created_at,
        updated_at=brand.updated_at,
    )


def product_variant_out(variant: ProductVariant) -> ProductVariantOut:
    return ProductVariantOut(
        id=variant.id,
        product_id=variant.product_id,
        name=variant.name,
        sku=variant.sku,
        barcode=variant.barcode,
        price_minor=variant.price_minor,
        cost_minor=variant.cost_minor,
        currency=variant.currency,
        attributes=variant.attributes,
        sale_price_minor=variant.sale_price_minor,
        manage_stock=variant.manage_stock,
        stock_quantity=variant.stock_quantity,
        stock_status=variant.stock_status,
        backorders=variant.backorders,
        weight=variant.weight,
        length=variant.length,
        width=variant.width,
        height=variant.height,
        shipping_class=variant.shipping_class,
        description=variant.description,
        image_url=variant.image_url,
        metadata=variant.metadata_json,
        is_active=variant.is_active,
    )


def product_image_out(image: ProductImage) -> ProductImageOut:
    return ProductImageOut(
        id=image.id,
        product_id=image.product_id,
        variant_id=image.variant_id,
        external_id=image.external_id,
        url=image.url,
        name=image.name,
        alt_text=image.alt_text,
        sort_order=image.sort_order,
        sync_status=image.sync_status,
        last_synced_at=image.last_synced_at,
    )


def product_out(db: Session, product: Product) -> ProductOut:
    return ProductOut(
        id=product.id,
        company_id=product.company_id,
        category_id=product.category_id,
        brand_id=product.brand_id,
        vendor_id=product.vendor_id,
        category_ids=product_category_ids(db, product.id),
        name=product.name,
        slug=product.slug,
        sku=product.sku,
        barcode=product.barcode,
        product_type=product.product_type,
        status=product.status,
        description=product.description,
        short_description=product.short_description,
        seo_title=product.seo_title,
        seo_description=product.seo_description,
        visibility=product.visibility,
        featured=product.featured,
        global_unique_id=product.global_unique_id,
        regular_price_minor=product.regular_price_minor,
        sale_price_minor=product.sale_price_minor,
        sale_start_at=product.sale_start_at,
        sale_end_at=product.sale_end_at,
        tax_status=product.tax_status,
        tax_class=product.tax_class,
        manage_stock=product.manage_stock,
        stock_quantity=product.stock_quantity,
        stock_status=product.stock_status,
        backorders=product.backorders,
        sold_individually=product.sold_individually,
        weight=product.weight,
        length=product.length,
        width=product.width,
        height=product.height,
        shipping_class=product.shipping_class,
        reviews_allowed=product.reviews_allowed,
        purchase_note=product.purchase_note,
        menu_order=product.menu_order,
        tags=product_tag_names(db, product.id),
        upsell_ids=product_relationship_ids(db, product.id, "upsell"),
        cross_sell_ids=product_relationship_ids(db, product.id, "cross_sell"),
        grouped_product_ids=product_relationship_ids(db, product.id, "grouped"),
        attributes=product.attributes,
        default_attributes=product.default_attributes,
        custom_metadata=product.custom_metadata,
        metadata=product.metadata_json,
        variants=[
            product_variant_out(variant)
            for variant in product_variants(db, product.id)
        ],
        images=[
            product_image_out(image)
            for image in product_images(db, product.id)
        ],
        created_at=product.created_at,
        updated_at=product.updated_at,
    )


def warehouse_out(warehouse: Warehouse) -> WarehouseOut:
    return WarehouseOut(
        id=warehouse.id,
        company_id=warehouse.company_id,
        code=warehouse.code,
        name=warehouse.name,
        address=warehouse.address,
        is_active=warehouse.is_active,
        created_at=warehouse.created_at,
        updated_at=warehouse.updated_at,
    )


def stock_movement_out(movement: StockMovement) -> StockMovementOut:
    return StockMovementOut(
        id=movement.id,
        company_id=movement.company_id,
        warehouse_id=movement.warehouse_id,
        product_id=movement.product_id,
        variant_id=movement.variant_id,
        movement_type=movement.movement_type,
        quantity_delta=movement.quantity_delta,
        reference_type=movement.reference_type,
        reference_id=movement.reference_id,
        transfer_group_id=movement.transfer_group_id,
        reason=movement.reason,
        metadata=movement.metadata_json,
        created_by_id=movement.created_by_id,
        occurred_at=movement.occurred_at,
        created_at=movement.created_at,
    )


def stock_level_out(level: StockLevel) -> StockLevelOut:
    return StockLevelOut(
        company_id=level.company_id,
        warehouse_id=level.warehouse_id,
        product_id=level.product_id,
        variant_id=level.variant_id,
        quantity_on_hand=level.quantity_on_hand,
    )


def customer_address_out(address: CustomerAddress) -> CustomerAddressOut:
    return CustomerAddressOut(
        id=address.id,
        customer_id=address.customer_id,
        label=address.label,
        recipient_name=address.recipient_name,
        phone=address.phone,
        line1=address.line1,
        line2=address.line2,
        city=address.city,
        state=address.state,
        postal_code=address.postal_code,
        country=address.country,
        is_default=address.is_default,
    )


def customer_note_out(note: CustomerNote) -> CustomerNoteOut:
    return CustomerNoteOut(
        id=note.id,
        customer_id=note.customer_id,
        created_by_id=note.created_by_id,
        note=note.note,
        created_at=note.created_at,
    )


def customer_out(db: Session, customer: Customer) -> CustomerOut:
    return CustomerOut(
        id=customer.id,
        company_id=customer.company_id,
        full_name=customer.full_name,
        source_channel=customer.source_channel,
        email=customer.email,
        phone=customer.phone,
        status=customer.status,
        credit_limit_minor=customer.credit_limit_minor,
        metadata=customer.metadata_json,
        addresses=[
            customer_address_out(address)
            for address in customer_addresses(db, customer.id)
        ],
        tags=customer_tags(db, customer.id),
        notes=[customer_note_out(note) for note in customer_notes(db, customer.id)],
        created_at=customer.created_at,
        updated_at=customer.updated_at,
    )


def order_item_out(item: OrderItem) -> OrderItemOut:
    return OrderItemOut(
        id=item.id,
        product_id=item.product_id,
        variant_id=item.variant_id,
        vendor_id=item.vendor_id,
        sku=item.sku,
        name=item.name,
        quantity=item.quantity,
        unit_price_minor=item.unit_price_minor,
        line_total_minor=item.line_total_minor,
        metadata=item.metadata_json,
    )


def order_status_history_out(entry: OrderStatusHistory) -> OrderStatusHistoryOut:
    return OrderStatusHistoryOut(
        id=entry.id,
        order_id=entry.order_id,
        from_status=entry.from_status,
        to_status=entry.to_status,
        changed_by_id=entry.changed_by_id,
        reason=entry.reason,
        created_at=entry.created_at,
    )


def payment_out(payment: Payment) -> PaymentOut:
    return PaymentOut(
        id=payment.id,
        order_id=payment.order_id,
        amount_minor=payment.amount_minor,
        currency=payment.currency,
        method=payment.method,
        status=payment.status,
        reference=payment.reference,
        paid_at=payment.paid_at,
        metadata=payment.metadata_json,
        created_at=payment.created_at,
    )


def order_out(db: Session, order: Order) -> OrderOut:
    return OrderOut(
        id=order.id,
        company_id=order.company_id,
        customer_id=order.customer_id,
        order_number=order.order_number,
        sales_channel=order.sales_channel,
        order_source=order.order_source,
        external_order_id=order.external_order_id,
        reservation_status=order.reservation_status,
        status=order.status,
        currency=order.currency,
        subtotal_minor=order.subtotal_minor,
        discount_minor=order.discount_minor,
        tax_minor=order.tax_minor,
        shipping_minor=order.shipping_minor,
        total_minor=order.total_minor,
        paid_minor=order.paid_minor,
        payment_status=order.payment_status,
        notes=order.notes,
        metadata=order.metadata_json,
        items=[order_item_out(item) for item in order_items(db, order.id)],
        payments=[payment_out(payment) for payment in order_payments(db, order.id)],
        status_history=[
            order_status_history_out(entry)
            for entry in order_status_history(db, order.id)
        ],
        created_at=order.created_at,
        updated_at=order.updated_at,
    )


def whatsapp_template_out(template: NotificationTemplate) -> WhatsAppTemplateOut:
    return WhatsAppTemplateOut(
        id=template.id,
        company_id=template.company_id,
        name=template.name,
        language=template.language,
        body=template.body,
        is_active=template.is_active,
        created_at=template.created_at,
        updated_at=template.updated_at,
    )


def whatsapp_message_out(message: NotificationQueue) -> WhatsAppMessageOut:
    return WhatsAppMessageOut(
        id=message.id,
        company_id=message.company_id,
        template_id=message.template_id,
        recipient_phone=message.recipient_phone,
        message_body=message.message_body,
        status=message.status,
        idempotency_key=message.idempotency_key,
        metadata=message.metadata_json,
        scheduled_at=message.scheduled_at,
        sent_at=message.sent_at,
        failed_at=message.failed_at,
        last_error=message.last_error,
        created_at=message.created_at,
        updated_at=message.updated_at,
    )


def whatsapp_delivery_log_out(log: NotificationDeliveryLog) -> WhatsAppDeliveryLogOut:
    return WhatsAppDeliveryLogOut(
        id=log.id,
        notification_id=log.notification_id,
        status=log.status,
        adapter=log.adapter,
        provider_message_id=log.provider_message_id,
        error=log.error,
        payload=log.payload,
        created_at=log.created_at,
    )


def dashboard_summary_out(summary: DashboardSummary) -> DashboardSummaryOut:
    return DashboardSummaryOut(
        sales_count=summary.sales_count,
        revenue_minor=summary.revenue_minor,
        pending_orders=summary.pending_orders,
        low_stock_count=summary.low_stock_count,
        customer_count=summary.customer_count,
        product_count=summary.product_count,
    )


def sales_report_row(item: SalesReportItem) -> SalesReportRow:
    return SalesReportRow(
        status=item.status,
        order_count=item.order_count,
        revenue_minor=item.revenue_minor,
    )


def inventory_report_row(item: InventoryReportItem) -> InventoryReportRow:
    return InventoryReportRow(
        product_id=item.product_id,
        variant_id=item.variant_id,
        warehouse_id=item.warehouse_id,
        quantity_on_hand=item.quantity_on_hand,
    )


def customer_report_row(customer: Customer) -> CustomerReportRow:
    return CustomerReportRow(
        id=customer.id,
        full_name=customer.full_name,
        phone=customer.phone,
        email=customer.email,
        status=customer.status,
    )


def order_report_row(order: Order) -> OrderReportRow:
    return OrderReportRow(
        id=order.id,
        order_number=order.order_number,
        customer_id=order.customer_id,
        status=order.status,
        total_minor=order.total_minor,
        paid_minor=order.paid_minor,
        payment_status=order.payment_status,
        created_at=order.created_at,
    )


def backup_metadata_out(metadata: BackupMetadata) -> BackupMetadataOut:
    return BackupMetadataOut(
        backup_id=metadata.backup_id,
        database_url_driver=metadata.database_url_driver,
        source_path=metadata.source_path,
        backup_path=metadata.backup_path,
        metadata_path=metadata.metadata_path,
        size_bytes=metadata.size_bytes,
        created_at=metadata.created_at,
    )


def restore_plan_out(plan: RestorePlan) -> RestorePlanOut:
    return RestorePlanOut(
        safe_to_restore=plan.safe_to_restore,
        backup_path=plan.backup_path,
        size_bytes=plan.size_bytes,
        strategy=plan.strategy,
        requires_confirmation=plan.requires_confirmation,
        detail=plan.detail,
    )


def license_status_out(state: LicenseState) -> LicenseStatusOut:
    return LicenseStatusOut(
        configured=state.configured,
        status=state.status,
        plan=state.plan,
        activated_at=state.activated_at,
        expires_at=state.expires_at,
        grace_expires_at=state.grace_expires_at,
        license_id=state.license_id,
        device_id=state.device_id,
        activation_mode=state.activation_mode,
        last_validated_at=state.last_validated_at,
    )


def license_validation_out(validation: LicenseValidation) -> LicenseValidationOut:
    return LicenseValidationOut(
        configured=validation.configured,
        status=validation.status,
        detail=validation.detail,
        validated_at=validation.validated_at,
    )


def diagnostics_summary_out(summary: DiagnosticsSummary) -> DiagnosticsSummaryOut:
    return DiagnosticsSummaryOut(
        app_version=summary.app_version,
        environment=summary.environment,
        database_driver=summary.database_driver,
        migration_revision=summary.migration_revision,
        expected_migration_revision=summary.expected_migration_revision,
        database_ready=summary.database_ready,
        company_id=summary.company_id,
        module_count=summary.module_count,
        settings=summary.settings,
        runtime=summary.runtime,
        generated_at=summary.generated_at,
    )


def woocommerce_config_out(db: Session, company_id: str | None) -> WooCommerceConfigOut:
    config = load_woocommerce_config(db, company_id)
    status = (
        woocommerce_sync_outbox_status(db, company_id)
        if company_id is not None
        else {
            "pending_product_pushes": 0,
            "pending_media_pushes": 0,
            "failed_product_pushes": 0,
            "failed_media_pushes": 0,
            "last_media_error": None,
        }
    )
    job_status = (
        woocommerce_sync_job_status(db, company_id)
        if company_id is not None
        else {
            "queued_sync_runs": 0,
            "running_sync_runs": 0,
            "active_sync_run_id": None,
            "active_sync_worker_id": None,
        }
    )
    if config is None:
        return WooCommerceConfigOut(
            configured=False,
            site_url=None,
            consumer_key_hint=None,
            wordpress_username=None,
            wordpress_media_configured=False,
            webhook_secret_configured=False,
            pending_product_pushes=int(status["pending_product_pushes"]),
            pending_media_pushes=int(status["pending_media_pushes"]),
            failed_product_pushes=int(status["failed_product_pushes"]),
            failed_media_pushes=int(status["failed_media_pushes"]),
            last_media_error=(
                str(status["last_media_error"]) if status["last_media_error"] else None
            ),
            queued_sync_runs=int(job_status["queued_sync_runs"]),
            running_sync_runs=int(job_status["running_sync_runs"]),
            active_sync_run_id=(
                str(job_status["active_sync_run_id"])
                if job_status["active_sync_run_id"]
                else None
            ),
            active_sync_worker_id=(
                str(job_status["active_sync_worker_id"])
                if job_status["active_sync_worker_id"]
                else None
            ),
            updated_at=None,
        )
    setting = db.scalar(
        select(Setting).where(
            Setting.company_id == company_id,
            Setting.key == "woocommerce.credentials",
        )
    )
    return WooCommerceConfigOut(
        configured=True,
        site_url=config.site_url,
        consumer_key_hint=config.key_hint,
        wordpress_username=config.wordpress_username,
        wordpress_media_configured=bool(
            config.wordpress_username and config.wordpress_application_password
        ),
        webhook_secret_configured=bool(config.webhook_secret),
        pending_product_pushes=int(status["pending_product_pushes"]),
        pending_media_pushes=int(status["pending_media_pushes"]),
        failed_product_pushes=int(status["failed_product_pushes"]),
        failed_media_pushes=int(status["failed_media_pushes"]),
        last_media_error=str(status["last_media_error"]) if status["last_media_error"] else None,
        queued_sync_runs=int(job_status["queued_sync_runs"]),
        running_sync_runs=int(job_status["running_sync_runs"]),
        active_sync_run_id=(
            str(job_status["active_sync_run_id"])
            if job_status["active_sync_run_id"]
            else None
        ),
        active_sync_worker_id=(
            str(job_status["active_sync_worker_id"])
            if job_status["active_sync_worker_id"]
            else None
        ),
        updated_at=setting.updated_at if setting is not None else None,
    )


def verify_woocommerce_webhook_signature(
    *,
    raw_body: bytes,
    signature: str | None,
    webhook_secret: str,
) -> None:
    if not signature:
        raise HTTPException(
            status_code=401,
            detail="Missing WooCommerce webhook signature.",
        )
    digest = hmac.new(webhook_secret.encode("utf-8"), raw_body, hashlib.sha256).digest()
    expected_signature = base64.b64encode(digest).decode("ascii")
    if not hmac.compare_digest(expected_signature, signature.strip()):
        raise HTTPException(
            status_code=401,
            detail="Invalid WooCommerce webhook signature.",
        )


def sync_run_log_out(run_log: SyncRunLog) -> SyncRunLogOut:
    return SyncRunLogOut(
        id=run_log.id,
        company_id=run_log.company_id,
        connector=run_log.connector,
        direction=run_log.direction,
        started_at=run_log.started_at,
        finished_at=run_log.finished_at,
        status=run_log.status,
        stats=run_log.stats,
        error=run_log.error,
        attempts=run_log.attempts,
        worker_id=run_log.worker_id,
        lease_expires_at=run_log.lease_expires_at,
    )


def sync_conflict_out(conflict: SyncConflict) -> SyncConflictOut:
    return SyncConflictOut(
        id=conflict.id,
        company_id=conflict.company_id,
        connector=conflict.connector,
        resource_type=conflict.resource_type,
        resource_id=conflict.resource_id,
        external_resource_id=conflict.external_resource_id,
        conflict_type=conflict.conflict_type,
        local_payload=conflict.local_payload,
        remote_payload=conflict.remote_payload,
        status=conflict.status,
        resolution=conflict.resolution,
        created_at=conflict.created_at,
        updated_at=conflict.updated_at,
    )


@router.get("/setup/status", response_model=SetupStatus, tags=["setup"])
def setup_status(db: DbSession) -> SetupStatus:
    return SetupStatus(is_configured=is_configured(db))


@router.post("/setup/first-use", response_model=AuthResponse, tags=["setup"])
def first_use_setup(
    payload: FirstUseSetupRequest,
    request: Request,
    db: DbSession,
    user_agent: Annotated[str | None, Header()] = None,
    x_bootstrap_token: Annotated[str | None, Header(alias="X-Bootstrap-Token")] = None,
) -> AuthResponse:
    try:
        issued = setup_first_use(
            db,
            payload,
            user_agent=user_agent,
            bootstrap_token=x_bootstrap_token,
            settings=getattr(request.app.state, "settings", get_settings()),
        )
        db.commit()
        return auth_response(issued)
    except ServiceError as exc:
        db.rollback()
        raise service_error_to_http(exc) from exc


@router.post("/auth/login", response_model=AuthResponse, tags=["identity"])
def login(
    payload: LoginRequest,
    request: Request,
    db: DbSession,
    user_agent: Annotated[str | None, Header()] = None,
) -> AuthResponse:
    try:
        issued = authenticate(
            db,
            username=payload.username,
            password=payload.password,
            company_id=payload.company_id,
            workspace_slug=payload.workspace_slug,
            user_agent=user_agent,
            ip_address=request.client.host if request.client else None,
            remember_me=payload.remember_me,
            refresh_capable=payload.supports_refresh,
        )
        db.commit()
        return auth_response(issued)
    except ServiceError as exc:
        if exc.status_code in {401, 409}:
            db.commit()
        else:
            db.rollback()
        raise service_error_to_http(exc) from exc


@router.get("/auth/me", response_model=CurrentUserResponse, tags=["identity"])
def me(context: CurrentContext, db: DbSession) -> CurrentUserResponse:
    return CurrentUserResponse(
        user=user_out(context.user, db),
        company=company_out(context.company),
        permissions=context.permissions,
        session_id=context.session.id,
        session_created_at=context.session.created_at,
        session_expires_at=context.session.expires_at,
        session_user_agent=context.session.user_agent,
    )


@router.post("/auth/refresh", response_model=AuthResponse, tags=["identity"])
def refresh_session(
    payload: RefreshRequest,
    request: Request,
    db: DbSession,
    user_agent: Annotated[str | None, Header()] = None,
) -> AuthResponse:
    if not payload.refresh_token:
        raise HTTPException(status_code=401, detail="Refresh token required.")
    try:
        issued = rotate_refresh_token(
            db,
            payload.refresh_token,
            user_agent=user_agent,
            ip_address=request.client.host if request.client else None,
        )
        db.commit()
        return auth_response(issued)
    except ServiceError as exc:
        # Reuse detection must be committed so the whole family remains revoked.
        if exc.status_code == 401:
            db.commit()
        else:
            db.rollback()
        raise service_error_to_http(exc) from exc


@router.post("/auth/logout", tags=["identity"])
def logout(
    context: OptionalCurrentContext,
    db: DbSession,
    payload: LogoutRequest | None = None,
) -> dict[str, bool]:
    all_sessions = payload.all_sessions if payload else False
    refresh_token = payload.refresh_token if payload else None
    if all_sessions and context is None:
        raise HTTPException(status_code=401, detail="Authenticated account authority is required.")
    if context is not None:
        revoke_session(
            db,
            context,
            refresh_token=refresh_token,
            all_sessions=all_sessions,
        )
    elif refresh_token:
        revoke_refresh_token(db, refresh_token)
    db.commit()
    return {"ok": True}


@router.post("/auth/change-password", status_code=204, tags=["identity"])
def auth_change_password(
    payload: PasswordChangeRequest,
    context: CurrentContext,
    db: DbSession,
) -> Response:
    try:
        change_password(
            db,
            context,
            current_password=payload.current_password,
            new_password=payload.new_password,
        )
        db.commit()
        return Response(status_code=204)
    except ServiceError as exc:
        db.rollback()
        raise service_error_to_http(exc) from exc


@router.post("/auth/password-reset/request", status_code=202, tags=["identity"])
def auth_password_reset_request(
    payload: PasswordResetRequest,
    request: Request,
    db: DbSession,
) -> dict[str, str]:
    settings = getattr(request.app.state, "settings", get_settings())
    if settings.is_production and (not settings.smtp_host or not settings.smtp_from_email):
        raise HTTPException(status_code=503, detail="Password-reset delivery is not configured.")
    scope_keys = auth_throttle_scope_keys(
        action="password_reset_request",
        account_identifier=payload.username_or_email,
        workspace=payload.workspace_slug,
        ip_address=request.client.host if request.client else None,
    )
    try:
        check_auth_throttle(db, scope_keys)
        user = find_password_reset_user(
            db,
            username_or_email=payload.username_or_email,
            workspace_slug=payload.workspace_slug,
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
        raise service_error_to_http(exc) from exc
    except OSError as exc:
        db.rollback()
        record_auth_throttle_attempt(db, scope_keys)
        db.commit()
        raise HTTPException(status_code=503, detail="Password-reset delivery failed.") from exc
    return {"message": "If the account exists, a reset link will be sent."}


@router.post("/auth/password-reset/confirm", status_code=204, tags=["identity"])
def auth_password_reset_confirm(
    payload: PasswordResetConfirm,
    request: Request,
    db: DbSession,
) -> Response:
    scope_keys = auth_throttle_scope_keys(
        action="password_reset_confirm",
        account_identifier=hash_session_token(payload.token),
        ip_address=request.client.host if request.client else None,
    )
    try:
        check_auth_throttle(db, scope_keys)
        confirm_password_reset(db, payload.token, payload.new_password)
        record_auth_throttle_attempt(db, scope_keys)
        db.commit()
        return Response(status_code=204)
    except ServiceError as exc:
        db.rollback()
        if exc.status_code != 429:
            record_auth_throttle_attempt(db, scope_keys)
            db.commit()
        raise service_error_to_http(exc) from exc


@router.post("/auth/activate", status_code=204, tags=["identity"])
def auth_activation_confirm(
    payload: ActivationConfirm,
    request: Request,
    db: DbSession,
) -> Response:
    scope_keys = auth_throttle_scope_keys(
        action="activation",
        account_identifier=hash_session_token(payload.token),
        ip_address=request.client.host if request.client else None,
    )
    try:
        check_auth_throttle(db, scope_keys)
        confirm_activation(db, payload.token, payload.password)
        record_auth_throttle_attempt(db, scope_keys)
        db.commit()
        return Response(status_code=204)
    except ServiceError as exc:
        db.rollback()
        if exc.status_code != 429:
            record_auth_throttle_attempt(db, scope_keys)
            db.commit()
        raise service_error_to_http(exc) from exc


@router.post(
    "/auth/register/vendor",
    response_model=RegistrationResponse,
    status_code=201,
    tags=["identity"],
)
def public_vendor_registration(
    payload: VendorRegistrationRequest,
    request: Request,
    db: DbSession,
) -> RegistrationResponse:
    scope_keys = auth_throttle_scope_keys(
        action="vendor_registration",
        account_identifier=payload.username,
        workspace=payload.workspace_slug,
        ip_address=request.client.host if request.client else None,
    )
    try:
        check_auth_throttle(db, scope_keys)
        created = register_public_vendor(db, payload)
        record_auth_throttle_attempt(db, scope_keys)
        db.commit()
        return RegistrationResponse(
            vendor_id=created.vendor.id,
            user_id=created.user.id,
            account_status=created.user.account_status,
            vendor_status=created.vendor.status,
            message="Registration received. An administrator must approve the vendor account.",
        )
    except ServiceError as exc:
        db.rollback()
        if exc.status_code != 429:
            record_auth_throttle_attempt(db, scope_keys)
            db.commit()
        raise service_error_to_http(exc) from exc
    except IntegrityError as exc:
        db.rollback()
        record_auth_throttle_attempt(db, scope_keys)
        db.commit()
        error = ServiceError(409, "Registration could not be completed.")
        raise service_error_to_http(error) from exc


@router.get("/identity/permissions", response_model=list[PermissionOut], tags=["identity"])
def permissions(
    _context: ManageRolesContext,
) -> list[PermissionOut]:
    return [
        PermissionOut(key=key, description=f"Permission: {key}")
        for key in declared_permissions()
    ]


@router.get("/identity/roles", response_model=list[RoleOut], tags=["identity"])
def roles(
    context: ManageRolesContext,
    db: DbSession,
) -> list[RoleOut]:
    return [role_out(db, role) for role in list_roles(db, context.user.company_id)]


@router.post("/identity/roles", response_model=RoleOut, status_code=201, tags=["identity"])
def identity_role_create(
    payload: RoleCreate,
    context: ManageRolesContext,
    db: DbSession,
) -> RoleOut:
    try:
        role = create_role(
            db,
            company_id=context.user.company_id,
            actor_user_id=context.user.id,
            payload=payload,
        )
        db.commit()
        return role_out(db, role)
    except ServiceError as exc:
        db.rollback()
        raise service_error_to_http(exc) from exc


@router.patch(
    "/identity/roles/{role_id}",
    response_model=RoleOut,
    status_code=200,
    tags=["identity"],
)
def identity_role_update(
    role_id: str,
    payload: RoleUpdate,
    context: ManageRolesContext,
    db: DbSession,
) -> RoleOut:
    try:
        role = update_role(
            db,
            company_id=context.user.company_id,
            actor_user_id=context.user.id,
            role_id=role_id,
            payload=payload,
        )
        db.commit()
        return role_out(db, role)
    except ServiceError as exc:
        db.rollback()
        raise service_error_to_http(exc) from exc


@router.get("/identity/users", response_model=list[UserOut], tags=["identity"])
def identity_users(
    context: UsersViewContext,
    db: DbSession,
) -> list[UserOut]:
    return [user_out(user, db) for user in list_users(db, context.user.company_id)]


@router.get(
    "/identity/users/{user_id}",
    response_model=AdminUserDetailOut,
    tags=["identity"],
)
def identity_user_detail(
    user_id: str,
    context: UsersViewContext,
    db: DbSession,
) -> AdminUserDetailOut:
    try:
        user = get_user(db, context.user.company_id, user_id)
        return admin_user_detail_out(user, db)
    except ServiceError as exc:
        raise service_error_to_http(exc) from exc


@router.post("/identity/users", response_model=UserOut, status_code=201, tags=["identity"])
def identity_user_create(
    payload: UserCreate,
    context: UsersManageContext,
    db: DbSession,
) -> UserOut:
    try:
        user = create_user(
            db,
            company_id=context.user.company_id,
            actor_user_id=context.user.id,
            payload=payload,
        )
        db.commit()
        return user_out(user, db)
    except ServiceError as exc:
        db.rollback()
        raise service_error_to_http(exc) from exc


@router.patch(
    "/identity/users/{user_id}",
    response_model=AdminUserDetailOut,
    status_code=200,
    tags=["identity"],
)
def identity_user_update(
    user_id: str,
    payload: AdminUserUpdate,
    context: UsersManageContext,
    db: DbSession,
) -> AdminUserDetailOut:
    try:
        user_payload = UserUpdate.model_validate(
            payload.model_dump(exclude={"vendor_profile"}, exclude_unset=True)
        )
        user = update_user_and_vendor(
            db,
            company_id=context.user.company_id,
            actor_user_id=context.user.id,
            user_id=user_id,
            user_payload=user_payload,
            vendor_payload=payload.vendor_profile,
        )
        db.commit()
        return admin_user_detail_out(user, db)
    except ServiceError as exc:
        db.rollback()
        raise service_error_to_http(exc) from exc
    except IntegrityError as exc:
        db.rollback()
        raise service_error_to_http(
            ServiceError(409, "User could not be updated because a value already exists.")
        ) from exc


@router.post("/identity/users/{user_id}/reset-password", response_model=UserOut, tags=["identity"])
def identity_user_reset_password(
    user_id: str,
    payload: UserPasswordReset,
    context: UsersManageContext,
    db: DbSession,
) -> UserOut:
    try:
        user = reset_user_password(
            db,
            company_id=context.user.company_id,
            actor_user_id=context.user.id,
            user_id=user_id,
            password=payload.password,
        )
        db.commit()
        return user_out(user, db)
    except ServiceError as exc:
        db.rollback()
        raise service_error_to_http(exc) from exc


@router.get("/tenancy/companies", response_model=list[CompanyOut], tags=["tenancy"])
def tenancy_companies(
    context: TenancyViewContext,
    db: DbSession,
) -> list[CompanyOut]:
    companies: list[CompanyOut] = []
    for company in list_companies(db, context.user.company_id):
        serialized = company_out(company)
        if serialized is not None:
            companies.append(serialized)
    return companies


@router.post("/tenancy/companies", response_model=CompanyOut, status_code=201, tags=["tenancy"])
def tenancy_company_create(
    payload: CompanyCreate,
    context: TenancyManageContext,
    db: DbSession,
) -> CompanyOut:
    try:
        company = create_company(
            db,
            requester_company_id=context.user.company_id,
            user_id=context.user.id,
            payload=payload,
        )
        db.commit()
        out = company_out(company)
        if out is None:
            raise HTTPException(status_code=500, detail="Company was not created.")
        return out
    except ServiceError as exc:
        db.rollback()
        raise service_error_to_http(exc) from exc


@router.patch(
    "/tenancy/companies/{company_id}",
    response_model=CompanyOut,
    status_code=200,
    tags=["tenancy"],
)
def tenancy_company_update(
    company_id: str,
    payload: CompanyUpdate,
    context: TenancyManageContext,
    db: DbSession,
) -> CompanyOut:
    try:
        company = update_company(
            db,
            requester_company_id=context.user.company_id,
            user_id=context.user.id,
            company_id=company_id,
            payload=payload,
        )
        db.commit()
        out = company_out(company)
        if out is None:
            raise HTTPException(status_code=500, detail="Company was not updated.")
        return out
    except ServiceError as exc:
        db.rollback()
        raise service_error_to_http(exc) from exc


@router.get("/catalog/categories", response_model=list[CategoryOut], tags=["catalog"])
def catalog_categories(
    context: CatalogViewContext,
    db: DbSession,
    include_archived: bool = False,
) -> list[CategoryOut]:
    try:
        return [
            category_out(category)
            for category in list_categories(
                db,
                context.user.company_id,
                include_archived=include_archived,
            )
        ]
    except ServiceError as exc:
        raise service_error_to_http(exc) from exc


@router.post("/catalog/categories", response_model=CategoryOut, status_code=201, tags=["catalog"])
def catalog_category_create(
    payload: CategoryCreate,
    context: CatalogManageContext,
    db: DbSession,
) -> CategoryOut:
    try:
        category = create_category(
            db,
            company_id=context.user.company_id,
            user_id=context.user.id,
            payload=payload,
        )
        db.commit()
        return category_out(category)
    except ServiceError as exc:
        db.rollback()
        raise service_error_to_http(exc) from exc


@router.get("/catalog/categories/{category_id}", response_model=CategoryOut, tags=["catalog"])
def catalog_category_detail(
    category_id: str,
    context: CatalogViewContext,
    db: DbSession,
) -> CategoryOut:
    try:
        return category_out(get_category(db, context.user.company_id, category_id))
    except ServiceError as exc:
        raise service_error_to_http(exc) from exc


@router.patch(
    "/catalog/categories/{category_id}",
    response_model=CategoryOut,
    status_code=200,
    tags=["catalog"],
)
def catalog_category_update(
    category_id: str,
    payload: CategoryUpdate,
    context: CatalogManageContext,
    db: DbSession,
) -> CategoryOut:
    try:
        category = update_category(
            db,
            company_id=context.user.company_id,
            user_id=context.user.id,
            category_id=category_id,
            payload=payload,
        )
        db.commit()
        return category_out(category)
    except ServiceError as exc:
        db.rollback()
        raise service_error_to_http(exc) from exc


@router.delete("/catalog/categories/{category_id}", status_code=200, tags=["catalog"])
def catalog_category_delete(
    category_id: str,
    context: CatalogManageContext,
    db: DbSession,
) -> dict[str, bool]:
    try:
        archive_category(
            db,
            company_id=context.user.company_id,
            user_id=context.user.id,
            category_id=category_id,
        )
        db.commit()
        return {"ok": True}
    except ServiceError as exc:
        db.rollback()
        raise service_error_to_http(exc) from exc


@router.get("/catalog/brands", response_model=list[BrandOut], tags=["catalog"])
def catalog_brands(
    context: CatalogViewContext,
    db: DbSession,
    include_archived: bool = False,
) -> list[BrandOut]:
    try:
        return [
            brand_out(brand)
            for brand in list_brands(
                db,
                context.user.company_id,
                include_archived=include_archived,
            )
        ]
    except ServiceError as exc:
        raise service_error_to_http(exc) from exc


@router.post("/catalog/brands", response_model=BrandOut, status_code=201, tags=["catalog"])
def catalog_brand_create(
    payload: BrandCreate,
    context: CatalogManageContext,
    db: DbSession,
) -> BrandOut:
    try:
        brand = create_brand(
            db,
            company_id=context.user.company_id,
            user_id=context.user.id,
            payload=payload,
        )
        db.commit()
        return brand_out(brand)
    except ServiceError as exc:
        db.rollback()
        raise service_error_to_http(exc) from exc


@router.get("/catalog/brands/{brand_id}", response_model=BrandOut, tags=["catalog"])
def catalog_brand_detail(
    brand_id: str,
    context: CatalogViewContext,
    db: DbSession,
) -> BrandOut:
    try:
        return brand_out(get_brand(db, context.user.company_id, brand_id))
    except ServiceError as exc:
        raise service_error_to_http(exc) from exc


@router.patch(
    "/catalog/brands/{brand_id}",
    response_model=BrandOut,
    status_code=200,
    tags=["catalog"],
)
def catalog_brand_update(
    brand_id: str,
    payload: BrandUpdate,
    context: CatalogManageContext,
    db: DbSession,
) -> BrandOut:
    try:
        brand = update_brand(
            db,
            company_id=context.user.company_id,
            user_id=context.user.id,
            brand_id=brand_id,
            payload=payload,
        )
        db.commit()
        return brand_out(brand)
    except ServiceError as exc:
        db.rollback()
        raise service_error_to_http(exc) from exc


@router.delete("/catalog/brands/{brand_id}", status_code=200, tags=["catalog"])
def catalog_brand_delete(
    brand_id: str,
    context: CatalogManageContext,
    db: DbSession,
) -> dict[str, bool]:
    try:
        archive_brand(
            db,
            company_id=context.user.company_id,
            user_id=context.user.id,
            brand_id=brand_id,
        )
        db.commit()
        return {"ok": True}
    except ServiceError as exc:
        db.rollback()
        raise service_error_to_http(exc) from exc


@router.get("/catalog/products", response_model=list[ProductOut], tags=["catalog"])
def catalog_products(
    context: CatalogViewContext,
    db: DbSession,
    include_archived: bool = False,
) -> list[ProductOut]:
    try:
        return [
            product_out(db, product)
            for product in list_products(
                db,
                context.user.company_id,
                include_archived=include_archived,
            )
        ]
    except ServiceError as exc:
        raise service_error_to_http(exc) from exc


@router.post("/catalog/products", response_model=ProductOut, status_code=201, tags=["catalog"])
def catalog_product_create(
    payload: ProductCreate,
    context: CatalogManageContext,
    db: DbSession,
) -> ProductOut:
    try:
        product = create_product(
            db,
            company_id=context.user.company_id,
            user_id=context.user.id,
            payload=payload,
        )
        _enqueue_product_sync_if_configured(
            db,
            company_id=context.user.company_id,
            product=product,
        )
        db.commit()
        return product_out(db, product)
    except ServiceError as exc:
        db.rollback()
        raise service_error_to_http(exc) from exc


@router.get(
    "/catalog/products/code-suggestion",
    response_model=ProductCodeSuggestionOut,
    tags=["catalog"],
)
def catalog_product_code_suggestion(
    context: CatalogViewContext,
    db: DbSession,
) -> ProductCodeSuggestionOut:
    try:
        sku, barcode = suggest_product_codes(db, context.user.company_id)
        return ProductCodeSuggestionOut(sku=sku, barcode=barcode)
    except ServiceError as exc:
        raise service_error_to_http(exc) from exc


@router.get("/catalog/products/{product_id}", response_model=ProductOut, tags=["catalog"])
def catalog_product_detail(
    product_id: str,
    context: CatalogViewContext,
    db: DbSession,
) -> ProductOut:
    try:
        return product_out(db, get_product(db, context.user.company_id, product_id))
    except ServiceError as exc:
        raise service_error_to_http(exc) from exc


@router.patch(
    "/catalog/products/{product_id}",
    response_model=ProductOut,
    status_code=200,
    tags=["catalog"],
)
def catalog_product_update(
    product_id: str,
    payload: ProductUpdate,
    context: CatalogManageContext,
    db: DbSession,
) -> ProductOut:
    try:
        product = update_product(
            db,
            company_id=context.user.company_id,
            user_id=context.user.id,
            product_id=product_id,
            payload=payload,
        )
        _enqueue_product_sync_if_configured(
            db,
            company_id=context.user.company_id,
            product=product,
        )
        db.commit()
        return product_out(db, product)
    except ServiceError as exc:
        db.rollback()
        raise service_error_to_http(exc) from exc


@router.post(
    "/catalog/products/{product_id}/images/upload",
    response_model=ProductImageOut,
    status_code=201,
    tags=["catalog"],
)
def catalog_product_image_upload(
    product_id: str,
    context: CatalogManageContext,
    db: DbSession,
    file: Annotated[UploadFile, File()],
) -> ProductImageOut:
    try:
        product = get_product(db, context.user.company_id, product_id)
        original_name = Path(file.filename or "product-image").name
        suffix = Path(original_name).suffix.lower()
        if suffix not in PRODUCT_IMAGE_EXTENSIONS:
            raise ServiceError(422, "Unsupported image extension.")
        content_type = (file.content_type or mimetypes.types_map.get(suffix) or "").lower()
        if content_type not in PRODUCT_IMAGE_MIME_TYPES:
            raise ServiceError(422, "Unsupported image content type.")

        settings = get_settings()
        relative_dir = Path("products") / product.company_id / product.id
        target_dir = Path(settings.media_upload_dir) / relative_dir
        target_dir.mkdir(parents=True, exist_ok=True)
        target_name = f"{uuid.uuid4().hex}{suffix}"
        target_path = target_dir / target_name

        size = 0
        with target_path.open("wb") as handle:
            while chunk := file.file.read(1024 * 1024):
                size += len(chunk)
                if size > PRODUCT_IMAGE_MAX_BYTES:
                    handle.close()
                    target_path.unlink(missing_ok=True)
                    raise ServiceError(413, "Product image is too large.")
                handle.write(chunk)

        image_count = len(product_images(db, product.id))
        image = ProductImage(
            company_id=product.company_id,
            product_id=product.id,
            url=f"/media/{relative_dir.as_posix()}/{target_name}",
            name=original_name[:255],
            alt_text=product.name,
            sort_order=image_count,
            sync_status="pending_add",
        )
        db.add(image)
        _enqueue_product_sync_if_configured(
            db,
            company_id=context.user.company_id,
            product=product,
        )
        db.commit()
        db.refresh(image)
        return product_image_out(image)
    except ServiceError as exc:
        db.rollback()
        raise service_error_to_http(exc) from exc


@router.delete("/catalog/products/{product_id}", status_code=200, tags=["catalog"])
def catalog_product_delete(
    product_id: str,
    context: CatalogManageContext,
    db: DbSession,
) -> dict[str, bool]:
    try:
        archive_product(
            db,
            company_id=context.user.company_id,
            user_id=context.user.id,
            product_id=product_id,
        )
        product = get_product(db, context.user.company_id, product_id)
        _enqueue_product_sync_if_configured(
            db,
            company_id=context.user.company_id,
            product=product,
        )
        db.commit()
        return {"ok": True}
    except ServiceError as exc:
        db.rollback()
        raise service_error_to_http(exc) from exc


@router.delete("/catalog/products/{product_id}/permanent", status_code=200, tags=["catalog"])
def catalog_product_permanent_delete(
    product_id: str,
    context: CatalogManageContext,
    db: DbSession,
) -> dict[str, bool]:
    try:
        permanently_delete_product(
            db,
            company_id=context.user.company_id,
            user_id=context.user.id,
            product_id=product_id,
        )
        db.commit()
        return {"ok": True}
    except ServiceError as exc:
        db.rollback()
        raise service_error_to_http(exc) from exc


@router.get("/inventory/warehouses", response_model=list[WarehouseOut], tags=["inventory"])
def inventory_warehouses(
    context: InventoryViewContext,
    db: DbSession,
    include_archived: bool = False,
) -> list[WarehouseOut]:
    try:
        return [
            warehouse_out(warehouse)
            for warehouse in list_warehouses(
                db,
                context.user.company_id,
                include_archived=include_archived,
            )
        ]
    except ServiceError as exc:
        raise service_error_to_http(exc) from exc


@router.post(
    "/inventory/warehouses",
    response_model=WarehouseOut,
    status_code=201,
    tags=["inventory"],
)
def inventory_warehouse_create(
    payload: WarehouseCreate,
    context: InventoryManageContext,
    db: DbSession,
) -> WarehouseOut:
    try:
        warehouse = create_warehouse(
            db,
            company_id=context.user.company_id,
            user_id=context.user.id,
            payload=payload,
        )
        db.commit()
        return warehouse_out(warehouse)
    except ServiceError as exc:
        db.rollback()
        raise service_error_to_http(exc) from exc


@router.get("/inventory/warehouses/{warehouse_id}", response_model=WarehouseOut, tags=["inventory"])
def inventory_warehouse_detail(
    warehouse_id: str,
    context: InventoryViewContext,
    db: DbSession,
) -> WarehouseOut:
    try:
        return warehouse_out(get_warehouse(db, context.user.company_id, warehouse_id))
    except ServiceError as exc:
        raise service_error_to_http(exc) from exc


@router.patch(
    "/inventory/warehouses/{warehouse_id}",
    response_model=WarehouseOut,
    status_code=200,
    tags=["inventory"],
)
def inventory_warehouse_update(
    warehouse_id: str,
    payload: WarehouseUpdate,
    context: InventoryManageContext,
    db: DbSession,
) -> WarehouseOut:
    try:
        warehouse = update_warehouse(
            db,
            company_id=context.user.company_id,
            user_id=context.user.id,
            warehouse_id=warehouse_id,
            payload=payload,
        )
        db.commit()
        return warehouse_out(warehouse)
    except ServiceError as exc:
        db.rollback()
        raise service_error_to_http(exc) from exc


@router.delete("/inventory/warehouses/{warehouse_id}", status_code=200, tags=["inventory"])
def inventory_warehouse_delete(
    warehouse_id: str,
    context: InventoryManageContext,
    db: DbSession,
) -> dict[str, bool]:
    try:
        archive_warehouse(
            db,
            company_id=context.user.company_id,
            user_id=context.user.id,
            warehouse_id=warehouse_id,
        )
        db.commit()
        return {"ok": True}
    except ServiceError as exc:
        db.rollback()
        raise service_error_to_http(exc) from exc


@router.get("/inventory/stock-movements", response_model=list[StockMovementOut], tags=["inventory"])
def inventory_stock_movements(
    context: InventoryViewContext,
    db: DbSession,
    warehouse_id: str | None = None,
    product_id: str | None = None,
) -> list[StockMovementOut]:
    try:
        return [
            stock_movement_out(movement)
            for movement in list_stock_movements(
                db,
                context.user.company_id,
                warehouse_id=warehouse_id,
                product_id=product_id,
            )
        ]
    except ServiceError as exc:
        raise service_error_to_http(exc) from exc


@router.post(
    "/inventory/stock-movements",
    response_model=StockMovementOut,
    status_code=201,
    tags=["inventory"],
)
def inventory_stock_movement_create(
    payload: StockMovementCreate,
    context: InventoryManageContext,
    db: DbSession,
) -> StockMovementOut:
    try:
        movement = record_stock_movement(
            db,
            company_id=context.user.company_id,
            user_id=context.user.id,
            payload=payload,
        )
        db.commit()
        return stock_movement_out(movement)
    except ServiceError as exc:
        db.rollback()
        raise service_error_to_http(exc) from exc


@router.get("/inventory/stock", response_model=list[StockLevelOut], tags=["inventory"])
def inventory_stock_levels(
    context: InventoryViewContext,
    db: DbSession,
    warehouse_id: str | None = None,
    product_id: str | None = None,
    variant_id: str | None = None,
) -> list[StockLevelOut]:
    try:
        return [
            stock_level_out(level)
            for level in stock_levels(
                db,
                context.user.company_id,
                warehouse_id=warehouse_id,
                product_id=product_id,
                variant_id=variant_id,
            )
        ]
    except ServiceError as exc:
        raise service_error_to_http(exc) from exc


@router.get("/customers", response_model=list[CustomerOut], tags=["customers"])
def customers_list(
    context: CustomersViewContext,
    db: DbSession,
    include_archived: bool = False,
) -> list[CustomerOut]:
    try:
        return [
            customer_out(db, customer)
            for customer in list_customers(
                db,
                context.user.company_id,
                include_archived=include_archived,
            )
        ]
    except ServiceError as exc:
        raise service_error_to_http(exc) from exc


@router.post("/customers", response_model=CustomerOut, status_code=201, tags=["customers"])
def customer_create(
    payload: CustomerCreate,
    context: CustomersManageContext,
    db: DbSession,
) -> CustomerOut:
    try:
        customer = create_customer(
            db,
            company_id=context.user.company_id,
            user_id=context.user.id,
            payload=payload,
        )
        db.commit()
        return customer_out(db, customer)
    except ServiceError as exc:
        db.rollback()
        raise service_error_to_http(exc) from exc


@router.get("/customers/{customer_id}", response_model=CustomerOut, tags=["customers"])
def customer_detail(
    customer_id: str,
    context: CustomersViewContext,
    db: DbSession,
) -> CustomerOut:
    try:
        return customer_out(db, get_customer(db, context.user.company_id, customer_id))
    except ServiceError as exc:
        raise service_error_to_http(exc) from exc


@router.patch(
    "/customers/{customer_id}",
    response_model=CustomerOut,
    status_code=200,
    tags=["customers"],
)
def customer_update(
    customer_id: str,
    payload: CustomerUpdate,
    context: CustomersManageContext,
    db: DbSession,
) -> CustomerOut:
    try:
        customer = update_customer(
            db,
            company_id=context.user.company_id,
            user_id=context.user.id,
            customer_id=customer_id,
            payload=payload,
        )
        db.commit()
        return customer_out(db, customer)
    except ServiceError as exc:
        db.rollback()
        raise service_error_to_http(exc) from exc


@router.delete("/customers/{customer_id}", status_code=200, tags=["customers"])
def customer_delete(
    customer_id: str,
    context: CustomersManageContext,
    db: DbSession,
) -> dict[str, bool]:
    try:
        archive_customer(
            db,
            company_id=context.user.company_id,
            user_id=context.user.id,
            customer_id=customer_id,
        )
        db.commit()
        return {"ok": True}
    except ServiceError as exc:
        db.rollback()
        raise service_error_to_http(exc) from exc


@router.post(
    "/customers/{customer_id}/addresses",
    response_model=CustomerAddressOut,
    status_code=201,
    tags=["customers"],
)
def customer_address_create(
    customer_id: str,
    payload: CustomerAddressCreate,
    context: CustomersManageContext,
    db: DbSession,
) -> CustomerAddressOut:
    try:
        address = add_customer_address(
            db,
            company_id=context.user.company_id,
            user_id=context.user.id,
            customer_id=customer_id,
            payload=payload,
        )
        db.commit()
        return customer_address_out(address)
    except ServiceError as exc:
        db.rollback()
        raise service_error_to_http(exc) from exc


@router.post(
    "/customers/{customer_id}/notes",
    response_model=CustomerNoteOut,
    status_code=201,
    tags=["customers"],
)
def customer_note_create(
    customer_id: str,
    payload: CustomerNoteCreate,
    context: CustomersManageContext,
    db: DbSession,
) -> CustomerNoteOut:
    try:
        note = add_customer_note(
            db,
            company_id=context.user.company_id,
            user_id=context.user.id,
            customer_id=customer_id,
            payload=payload,
        )
        db.commit()
        return customer_note_out(note)
    except ServiceError as exc:
        db.rollback()
        raise service_error_to_http(exc) from exc


@router.get("/orders", response_model=list[OrderOut], tags=["orders"])
def orders_list(
    context: OrdersViewContext,
    db: DbSession,
    status: str | None = None,
) -> list[OrderOut]:
    try:
        return [
            order_out(db, order)
            for order in list_orders(
                db,
                context.user.company_id,
                status=status,
            )
        ]
    except ServiceError as exc:
        raise service_error_to_http(exc) from exc


@router.post("/orders", response_model=OrderOut, status_code=201, tags=["orders"])
def order_create(
    payload: OrderCreate,
    context: OrdersManageContext,
    db: DbSession,
) -> OrderOut:
    try:
        order = create_order(
            db,
            company_id=context.user.company_id,
            user_id=context.user.id,
            payload=payload,
        )
        db.commit()
        return order_out(db, order)
    except ServiceError as exc:
        db.rollback()
        raise service_error_to_http(exc) from exc


@router.get("/orders/{order_id}", response_model=OrderOut, tags=["orders"])
def order_detail(
    order_id: str,
    context: OrdersViewContext,
    db: DbSession,
) -> OrderOut:
    try:
        return order_out(db, get_order(db, context.user.company_id, order_id))
    except ServiceError as exc:
        raise service_error_to_http(exc) from exc


@router.post("/orders/{order_id}/status", response_model=OrderOut, tags=["orders"])
def order_status_update(
    order_id: str,
    payload: OrderStatusChange,
    context: OrdersManageContext,
    db: DbSession,
) -> OrderOut:
    try:
        order = change_order_status(
            db,
            company_id=context.user.company_id,
            user_id=context.user.id,
            order_id=order_id,
            payload=payload,
        )
        db.commit()
        return order_out(db, order)
    except ServiceError as exc:
        db.rollback()
        raise service_error_to_http(exc) from exc


@router.post(
    "/orders/{order_id}/payments",
    response_model=PaymentOut,
    status_code=201,
    tags=["orders"],
)
def order_payment_create(
    order_id: str,
    payload: PaymentCreate,
    context: OrdersManageContext,
    db: DbSession,
) -> PaymentOut:
    try:
        payment = record_payment(
            db,
            company_id=context.user.company_id,
            user_id=context.user.id,
            order_id=order_id,
            payload=payload,
        )
        db.commit()
        return payment_out(payment)
    except ServiceError as exc:
        db.rollback()
        raise service_error_to_http(exc) from exc


@router.get(
    "/woocommerce/config",
    response_model=WooCommerceConfigOut,
    tags=["woocommerce"],
)
def woocommerce_config_get(
    context: WooCommerceViewContext,
    db: DbSession,
) -> WooCommerceConfigOut:
    try:
        return woocommerce_config_out(db, context.user.company_id)
    except ServiceError as exc:
        raise service_error_to_http(exc) from exc


@router.put(
    "/woocommerce/config",
    response_model=WooCommerceConfigOut,
    status_code=200,
    tags=["woocommerce"],
)
def woocommerce_config_update(
    payload: WooCommerceConfigRequest,
    context: WooCommerceConfigureContext,
    db: DbSession,
) -> WooCommerceConfigOut:
    try:
        configure_woocommerce(
            db,
            company_id=context.user.company_id,
            user_id=context.user.id,
            payload=payload,
        )
        db.commit()
        return woocommerce_config_out(db, context.user.company_id)
    except ServiceError as exc:
        db.rollback()
        raise service_error_to_http(exc) from exc


@router.post(
    "/woocommerce/test-connection",
    response_model=WooCommerceConnectionTestOut,
    tags=["woocommerce"],
)
def woocommerce_connection_test(
    context: WooCommerceConfigureContext,
    db: DbSession,
) -> WooCommerceConnectionTestOut:
    try:
        result = test_woocommerce_connection(db, context.user.company_id)
        db.commit()
        return WooCommerceConnectionTestOut(
            ok=result.ok,
            status=result.status,
            detail=result.detail,
        )
    except ServiceError as exc:
        raise service_error_to_http(exc) from exc


@router.post(
    "/woocommerce/sync",
    response_model=SyncRunLogOut,
    status_code=202,
    tags=["woocommerce"],
)
def woocommerce_sync_trigger(
    context: DashboardWooCommerceSyncContext,
    db: DbSession,
    mode: str = "incremental",
) -> SyncRunLogOut:
    try:
        vendor_id = None
        if "woocommerce.sync" not in context.permissions:
            vendor_id = vendor_for_user(db, context.user.company_id, context.user.id).id
        run_log, _created = enqueue_woocommerce_sync_run(
            db,
            company_id=context.user.company_id,
            sync_mode=mode,
            vendor_id=vendor_id,
        )
        db.commit()
        return sync_run_log_out(run_log)
    except ServiceError as exc:
        db.rollback()
        raise service_error_to_http(exc) from exc


@router.get(
    "/woocommerce/sync-runs",
    response_model=list[SyncRunLogOut],
    tags=["woocommerce"],
)
def woocommerce_sync_runs_list(
    context: DashboardWooCommerceSyncContext,
    db: DbSession,
) -> list[SyncRunLogOut]:
    try:
        vendor_id = None
        if "woocommerce.sync" not in context.permissions:
            vendor_id = vendor_for_user(db, context.user.company_id, context.user.id).id
        return [
            sync_run_log_out(log)
            for log in list_sync_runs(db, context.user.company_id, vendor_id=vendor_id)
        ]
    except ServiceError as exc:
        raise service_error_to_http(exc) from exc


@router.get(
    "/woocommerce/conflicts",
    response_model=list[SyncConflictOut],
    tags=["woocommerce"],
)
def woocommerce_conflicts_list(
    context: WooCommerceViewContext,
    db: DbSession,
) -> list[SyncConflictOut]:
    try:
        conflicts = list_sync_conflicts(db, context.user.company_id)
        return [sync_conflict_out(conflict) for conflict in conflicts]
    except ServiceError as exc:
        raise service_error_to_http(exc) from exc


@router.post(
    "/woocommerce/conflicts/{conflict_id}/resolve",
    response_model=SyncConflictOut,
    tags=["woocommerce"],
)
def woocommerce_conflict_resolve(
    conflict_id: str,
    payload: SyncConflictResolveRequest,
    context: WooCommerceSyncContext,
    db: DbSession,
) -> SyncConflictOut:
    try:
        conflict = resolve_sync_conflict(
            db,
            context.user.company_id,
            conflict_id,
            payload,
            user_id=context.user.id,
        )
        db.commit()
        return sync_conflict_out(conflict)
    except ServiceError as exc:
        db.rollback()
        raise service_error_to_http(exc) from exc


@router.post(
    "/woocommerce/webhooks",
    tags=["woocommerce"],
)
async def woocommerce_webhook_receiver(
    request: Request,
    db: DbSession,
    x_wc_webhook_topic: Annotated[str | None, Header()] = None,
    x_wc_webhook_delivery_id: Annotated[str | None, Header()] = None,
    x_wc_webhook_source: Annotated[str | None, Header()] = None,
    x_wc_webhook_signature: Annotated[str | None, Header()] = None,
) -> dict[str, bool]:
    company_id = None
    config = None
    raw_body = await request.body()
    if not x_wc_webhook_source:
        raise HTTPException(
            status_code=400,
            detail="WooCommerce webhook source is required.",
        )
    all_credentials = db.scalars(
        select(Setting).where(Setting.key == "woocommerce.credentials")
    ).all()
    for cred in all_credentials:
        try:
            cfg = load_woocommerce_config(db, cred.company_id)
            if cfg and cfg.site_url.rstrip("/") == x_wc_webhook_source.rstrip("/"):
                company_id = cred.company_id
                config = cfg
                break
        except Exception:
            continue

    if not company_id or config is None:
        raise HTTPException(
            status_code=400,
            detail="No registered company found for WooCommerce webhook.",
        )
    if not config.webhook_secret:
        raise HTTPException(
            status_code=403,
            detail="WooCommerce webhook secret is not configured for this company.",
        )
    verify_woocommerce_webhook_signature(
        raw_body=raw_body,
        signature=x_wc_webhook_signature,
        webhook_secret=config.webhook_secret,
    )
    try:
        payload = json.loads(raw_body.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=422, detail="Webhook payload must be valid JSON.") from exc
    if not isinstance(payload, dict):
        raise HTTPException(status_code=422, detail="Webhook payload must be a JSON object.")

    try:
        process_webhook_event(
            db,
            company_id=company_id,
            topic=x_wc_webhook_topic,
            delivery_id=x_wc_webhook_delivery_id,
            payload=payload,
        )
        db.commit()
        return {"ok": True}
    except ServiceError as exc:
        db.rollback()
        raise service_error_to_http(exc) from exc


@router.get(
    "/whatsapp/templates",
    response_model=list[WhatsAppTemplateOut],
    tags=["whatsapp"],
)
def whatsapp_templates_list(
    context: WhatsAppViewContext,
    db: DbSession,
) -> list[WhatsAppTemplateOut]:
    try:
        return [
            whatsapp_template_out(template)
            for template in list_templates(db, context.user.company_id)
        ]
    except ServiceError as exc:
        raise service_error_to_http(exc) from exc


@router.post(
    "/whatsapp/templates",
    response_model=WhatsAppTemplateOut,
    status_code=201,
    tags=["whatsapp"],
)
def whatsapp_template_create(
    payload: WhatsAppTemplateCreate,
    context: WhatsAppConfigureContext,
    db: DbSession,
) -> WhatsAppTemplateOut:
    try:
        template = create_template(
            db,
            company_id=context.user.company_id,
            user_id=context.user.id,
            payload=payload,
        )
        db.commit()
        return whatsapp_template_out(template)
    except ServiceError as exc:
        db.rollback()
        raise service_error_to_http(exc) from exc


@router.get(
    "/whatsapp/messages",
    response_model=list[WhatsAppMessageOut],
    tags=["whatsapp"],
)
def whatsapp_messages_list(
    context: WhatsAppViewContext,
    db: DbSession,
    status: str | None = None,
) -> list[WhatsAppMessageOut]:
    try:
        return [
            whatsapp_message_out(message)
            for message in list_messages(db, context.user.company_id, status=status)
        ]
    except ServiceError as exc:
        raise service_error_to_http(exc) from exc


@router.post(
    "/whatsapp/messages",
    response_model=WhatsAppMessageOut,
    tags=["whatsapp"],
)
def whatsapp_message_enqueue(
    payload: WhatsAppMessageEnqueue,
    context: WhatsAppSendContext,
    db: DbSession,
) -> WhatsAppMessageOut:
    try:
        message = enqueue_message(
            db,
            company_id=context.user.company_id,
            user_id=context.user.id,
            payload=payload,
        )
        db.commit()
        return whatsapp_message_out(message)
    except ServiceError as exc:
        db.rollback()
        raise service_error_to_http(exc) from exc


@router.post(
    "/whatsapp/messages/{message_id}/mock-send",
    response_model=WhatsAppDeliveryLogOut,
    tags=["whatsapp"],
)
def whatsapp_message_mock_send(
    message_id: str,
    payload: WhatsAppMockSendRequest,
    context: WhatsAppSendContext,
    db: DbSession,
) -> WhatsAppDeliveryLogOut:
    try:
        log = deliver_with_mock_adapter(
            db,
            company_id=context.user.company_id,
            user_id=context.user.id,
            message_id=message_id,
            force_failure=payload.force_failure,
        )
        db.commit()
        return whatsapp_delivery_log_out(log)
    except ServiceError as exc:
        db.rollback()
        raise service_error_to_http(exc) from exc


@router.get(
    "/whatsapp/messages/{message_id}/delivery-logs",
    response_model=list[WhatsAppDeliveryLogOut],
    tags=["whatsapp"],
)
def whatsapp_message_delivery_logs(
    message_id: str,
    context: WhatsAppViewContext,
    db: DbSession,
) -> list[WhatsAppDeliveryLogOut]:
    try:
        return [
            whatsapp_delivery_log_out(log)
            for log in delivery_logs(db, context.user.company_id, message_id)
        ]
    except ServiceError as exc:
        raise service_error_to_http(exc) from exc


@router.get(
    "/reports/dashboard-summary",
    response_model=DashboardSummaryOut,
    tags=["reports"],
)
def reports_dashboard_summary(
    context: ReportsViewContext,
    db: DbSession,
) -> DashboardSummaryOut:
    try:
        return dashboard_summary_out(dashboard_summary(db, context.user.company_id))
    except ServiceError as exc:
        raise service_error_to_http(exc) from exc


@router.get("/reports/sales", response_model=list[SalesReportRow], tags=["reports"])
def reports_sales(
    context: ReportsViewContext,
    db: DbSession,
) -> list[SalesReportRow]:
    try:
        return [sales_report_row(item) for item in sales_report(db, context.user.company_id)]
    except ServiceError as exc:
        raise service_error_to_http(exc) from exc


@router.get("/reports/inventory", response_model=list[InventoryReportRow], tags=["reports"])
def reports_inventory(
    context: ReportsViewContext,
    db: DbSession,
) -> list[InventoryReportRow]:
    try:
        return [
            inventory_report_row(item)
            for item in inventory_report(db, context.user.company_id)
        ]
    except ServiceError as exc:
        raise service_error_to_http(exc) from exc


@router.get("/reports/customers", response_model=list[CustomerReportRow], tags=["reports"])
def reports_customers(
    context: ReportsViewContext,
    db: DbSession,
) -> list[CustomerReportRow]:
    try:
        return [
            customer_report_row(customer)
            for customer in customer_report(db, context.user.company_id)
        ]
    except ServiceError as exc:
        raise service_error_to_http(exc) from exc


@router.get("/reports/orders", response_model=list[OrderReportRow], tags=["reports"])
def reports_orders(
    context: ReportsViewContext,
    db: DbSession,
) -> list[OrderReportRow]:
    try:
        return [order_report_row(order) for order in order_report(db, context.user.company_id)]
    except ServiceError as exc:
        raise service_error_to_http(exc) from exc


@router.get("/reports/orders.csv", tags=["reports"])
def reports_orders_csv(
    context: ReportsExportContext,
    db: DbSession,
) -> Response:
    try:
        csv_payload = orders_csv(db, context.user.company_id)
    except ServiceError as exc:
        raise service_error_to_http(exc) from exc
    return Response(
        content=csv_payload,
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="orders.csv"'},
    )


@router.post(
    "/backup/sqlite",
    response_model=BackupMetadataOut,
    tags=["backup"],
)
def backup_sqlite_create(
    context: BackupCreateContext,
    db: DbSession,
) -> BackupMetadataOut:
    try:
        metadata = create_sqlite_backup(
            db,
            company_id=context.user.company_id,
            user_id=context.user.id,
        )
        db.commit()
        return backup_metadata_out(metadata)
    except ServiceError as exc:
        db.rollback()
        raise service_error_to_http(exc) from exc


@router.post(
    "/backup/restore-plan",
    response_model=RestorePlanOut,
    tags=["backup"],
)
def backup_restore_plan(
    payload: RestorePlanRequest,
    _context: BackupRestoreContext,
) -> RestorePlanOut:
    return restore_plan_out(build_restore_plan(payload.backup_path))


@router.get(
    "/licensing/status",
    response_model=LicenseStatusOut,
    tags=["licensing"],
)
def licensing_status(
    context: LicensingViewContext,
    db: DbSession,
) -> LicenseStatusOut:
    try:
        return license_status_out(license_state(db, context.user.company_id))
    except ServiceError as exc:
        raise service_error_to_http(exc) from exc


@router.post(
    "/licensing/activate",
    response_model=LicenseStatusOut,
    tags=["licensing"],
)
def licensing_activate(
    payload: LicenseActivationRequest,
    context: LicensingManageContext,
    db: DbSession,
) -> LicenseStatusOut:
    try:
        activate_license(
            db,
            company_id=context.user.company_id,
            user_id=context.user.id,
            license_key=payload.license_key,
            plan=payload.plan,
        )
        db.commit()
        return license_status_out(license_state(db, context.user.company_id))
    except ServiceError as exc:
        db.rollback()
        raise service_error_to_http(exc) from exc


@router.post(
    "/licensing/validate",
    response_model=LicenseValidationOut,
    tags=["licensing"],
)
def licensing_validate(
    context: LicensingViewContext,
    db: DbSession,
) -> LicenseValidationOut:
    try:
        return license_validation_out(validate_license(db, context.user.company_id))
    except ServiceError as exc:
        raise service_error_to_http(exc) from exc


@router.post(
    "/licensing/revoke",
    response_model=LicenseStatusOut,
    tags=["licensing"],
)
def licensing_revoke(
    payload: LicenseRevokeRequest,
    context: LicensingManageContext,
    db: DbSession,
) -> LicenseStatusOut:
    try:
        revoke_license(
            db,
            company_id=context.user.company_id,
            user_id=context.user.id,
            reason=payload.reason,
        )
        db.commit()
        return license_status_out(license_state(db, context.user.company_id))
    except ServiceError as exc:
        db.rollback()
        raise service_error_to_http(exc) from exc


@router.get(
    "/support/diagnostics",
    response_model=DiagnosticsSummaryOut,
    tags=["support"],
)
def support_diagnostics(
    context: SupportViewContext,
    db: DbSession,
) -> DiagnosticsSummaryOut:
    return diagnostics_summary_out(diagnostics_summary(db, context.user.company_id))


@router.get("/support/diagnostics.zip", tags=["support"])
def support_diagnostics_zip(
    context: SupportViewContext,
    db: DbSession,
) -> Response:
    filename, payload = create_diagnostics_zip(
        db,
        company_id=context.user.company_id,
        user_id=context.user.id,
    )
    db.commit()
    return Response(
        content=payload,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/settings", response_model=list[SettingOut], tags=["settings"])
def settings_list(
    context: SettingsViewContext,
    db: DbSession,
) -> list[SettingOut]:
    return [setting_out(setting) for setting in list_settings(db, context.user.company_id)]


@router.put("/settings/{key}", response_model=SettingOut, status_code=200, tags=["settings"])
def settings_update(
    key: str,
    payload: SettingUpdateRequest,
    context: SettingsManageContext,
    db: DbSession,
) -> SettingOut:
    if not SETTING_KEY_PATTERN.fullmatch(key):
        raise HTTPException(status_code=422, detail="Invalid setting key.")
    setting = upsert_setting(
        db,
        company_id=context.user.company_id,
        key=key,
        value=payload.value,
        user_id=context.user.id,
    )
    db.commit()
    return setting_out(setting)


@router.get("/audit-logs", response_model=list[AuditLogOut], tags=["audit"])
def audit_logs(
    context: AuditViewContext,
    db: DbSession,
    limit: int = 100,
) -> list[AuditLogOut]:
    safe_limit = max(1, min(limit, 500))
    return [
        audit_log_out(entry)
        for entry in list_audit_logs(db, context.user.company_id, safe_limit)
    ]
