"""Shared serializer functions used across route modules."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from erp.packages.core.backup_services import BackupMetadata, RestorePlan
from erp.packages.core.catalog_services import (
    product_category_ids,
    product_images,
    product_relationship_ids,
    product_tag_names,
    product_variants,
)
from erp.packages.core.customer_services import (
    customer_addresses,
    customer_notes,
    customer_tags,
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
    User,
    Warehouse,
)
from erp.packages.core.inventory_services import StockLevel
from erp.packages.core.licensing_services import LicenseState
from erp.packages.core.order_services import (
    order_items,
    order_payments,
    order_status_history,
)
from erp.packages.core.report_services import (
    DashboardSummary,
    InventoryReportItem,
    SalesReportItem,
)
from erp.packages.core.schemas import (
    AuditLogOut,
    AuthResponse,
    BackupMetadataOut,
    BrandOut,
    CategoryOut,
    CompanyOut,
    CustomerAddressOut,
    CustomerNoteOut,
    CustomerOut,
    CustomerReportRow,
    DashboardSummaryOut,
    InventoryReportRow,
    LicenseStatusOut,
    OrderItemOut,
    OrderOut,
    OrderReportRow,
    OrderStatusHistoryOut,
    PaymentOut,
    ProductImageOut,
    ProductOut,
    ProductVariantOut,
    RestorePlanOut,
    RoleOut,
    SalesReportRow,
    SettingOut,
    StockLevelOut,
    StockMovementOut,
    UserOut,
    WarehouseOut,
    WhatsAppDeliveryLogOut,
    WhatsAppMessageOut,
    WhatsAppTemplateOut,
    WooCommerceConfigOut,
)
from erp.packages.core.services import IssuedSession, role_permissions
from erp.packages.core.woocommerce_services import (
    load_woocommerce_config,
    woocommerce_sync_outbox_status,
)


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


def user_out(user: User) -> UserOut:
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
    )


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
        variants=[product_variant_out(v) for v in product_variants(db, product.id)],
        images=[product_image_out(img) for img in product_images(db, product.id)],
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
            customer_address_out(addr)
            for addr in customer_addresses(db, customer.id)
        ],
        tags=customer_tags(db, customer.id),
        notes=[
            customer_note_out(note)
            for note in customer_notes(db, customer.id)
        ],
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


def order_status_history_out(
    entry: OrderStatusHistory,
) -> OrderStatusHistoryOut:
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
        items=[
            order_item_out(item) for item in order_items(db, order.id)
        ],
        payments=[
            payment_out(p) for p in order_payments(db, order.id)
        ],
        status_history=[
            order_status_history_out(e)
            for e in order_status_history(db, order.id)
        ],
        created_at=order.created_at,
        updated_at=order.updated_at,
    )


def whatsapp_template_out(
    template: NotificationTemplate,
) -> WhatsAppTemplateOut:
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


def whatsapp_delivery_log_out(
    log: NotificationDeliveryLog,
) -> WhatsAppDeliveryLogOut:
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
    )


def woocommerce_config_out(
    db: Session, company_id: str | None,
) -> WooCommerceConfigOut:
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
        updated_at=setting.updated_at if setting is not None else None,
    )
