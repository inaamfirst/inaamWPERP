from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from erp.packages.core.accounting_services import (
    generate_entry_number,
    post_vendor_settlement_entry,
    vendor_balance_minor,
)
from erp.packages.core.catalog_services import require_company_id
from erp.packages.core.db.models import (
    MarketplaceCommissionRule,
    Order,
    OrderItem,
    Product,
    ProductVariant,
    User,
    UserRole,
    Vendor,
    VendorNotification,
    VendorOrderItem,
    VendorOrderItemStatusHistory,
    VendorProduct,
    VendorSettlement,
    VendorUser,
)
from erp.packages.core.schemas import (
    CommissionRuleCreate,
    CommissionRuleOut,
    CommissionRuleUpdate,
    VendorCreate,
    VendorNotificationOut,
    VendorOrderItemOut,
    VendorOrderItemStatusChange,
    VendorOut,
    VendorProductAssignRequest,
    VendorProductOut,
    VendorSettlementCreate,
    VendorSettlementOut,
    VendorUpdate,
    VendorUserCreate,
    VendorUserOut,
)
from erp.packages.core.services import ServiceError, record_audit, to_utc, utcnow
from erp.packages.core.vendor_auth_services import change_vendor_status

SLUG_SEPARATOR_PATTERN = re.compile(r"[^a-z0-9]+")
VENDOR_STATUSES = {"pending", "active", "paused", "stopped"}
VENDOR_STATUS_ALIASES = {
    "approved": "active",
    "suspended": "paused",
    "rejected": "stopped",
}
VENDOR_STATUS_STORAGE_VALUES = {
    "active": {"active", "approved"},
    "pending": {"pending"},
    "paused": {"paused", "suspended"},
    "stopped": {"stopped", "rejected"},
}
VENDOR_PRODUCT_STATUSES = {"submitted", "approved", "rejected", "published", "archived"}
VENDOR_ORDER_ITEM_TRANSITIONS = {
    "pending": {"accepted", "rejected"},
    "accepted": {"packing"},
    "packing": {"dispatched"},
    "dispatched": {"delivered"},
    "delivered": set(),
    "rejected": set(),
}


def slugify(value: str) -> str:
    slug = SLUG_SEPARATOR_PATTERN.sub("-", value.strip().lower()).strip("-")
    if not slug:
        raise ServiceError(422, "A valid slug could not be generated.")
    return slug[:160]


def normalize_vendor_slug(name: str, slug: str | None = None) -> str:
    return slugify(slug or name)


def normalize_vendor_status(status: str) -> str:
    normalized = status.strip().lower()
    normalized = VENDOR_STATUS_ALIASES.get(normalized, normalized)
    if normalized not in VENDOR_STATUSES:
        raise ServiceError(422, f"Unsupported vendor status: {status}.")
    return normalized


def normalize_vendor_product_status(status: str) -> str:
    normalized = status.strip().lower()
    if normalized not in VENDOR_PRODUCT_STATUSES:
        raise ServiceError(422, f"Unsupported vendor product status: {status}.")
    return normalized


def vendor_out(vendor: Vendor) -> VendorOut:
    access_status = VENDOR_STATUS_ALIASES.get(
        vendor.status.strip().lower(), vendor.status.strip().lower()
    )
    if access_status not in VENDOR_STATUSES:
        access_status = "stopped"
    return VendorOut(
        id=vendor.id,
        company_id=vendor.company_id,
        name=vendor.name,
        slug=vendor.slug,
        legal_name=vendor.legal_name,
        contact_name=vendor.contact_name,
        email=vendor.email,
        phone=vendor.phone,
        status=vendor.status,
        access_status=access_status,
        default_commission_bps=vendor.default_commission_bps,
        metadata=vendor.metadata_json,
        created_at=vendor.created_at,
        updated_at=vendor.updated_at,
    )


def vendor_user_out(vendor_user: VendorUser) -> VendorUserOut:
    return VendorUserOut(
        id=vendor_user.id,
        company_id=vendor_user.company_id,
        vendor_id=vendor_user.vendor_id,
        user_id=vendor_user.user_id,
        role_name=vendor_user.role_name,
        is_primary=vendor_user.is_primary,
        metadata=vendor_user.metadata_json,
        created_at=vendor_user.created_at,
        updated_at=vendor_user.updated_at,
    )


def vendor_product_out(vendor_product: VendorProduct) -> VendorProductOut:
    return VendorProductOut(
        id=vendor_product.id,
        company_id=vendor_product.company_id,
        vendor_id=vendor_product.vendor_id,
        product_id=vendor_product.product_id,
        ownership_type=vendor_product.ownership_type,
        approval_status=vendor_product.approval_status,
        approved_by_id=vendor_product.approved_by_id,
        approved_at=vendor_product.approved_at,
        rejected_reason=vendor_product.rejected_reason,
        published_at=vendor_product.published_at,
        metadata=vendor_product.metadata_json,
        created_at=vendor_product.created_at,
        updated_at=vendor_product.updated_at,
    )


def vendor_order_item_out(
    item: VendorOrderItem,
    *,
    db: Session | None = None,
) -> VendorOrderItemOut:
    order = (
        db.scalar(
            select(Order).where(
                Order.company_id == item.company_id,
                Order.id == item.order_id,
            )
        )
        if db is not None
        else None
    )
    return VendorOrderItemOut(
        id=item.id,
        company_id=item.company_id,
        vendor_id=item.vendor_id,
        order_id=item.order_id,
        order_item_id=item.order_item_id,
        product_id=item.product_id,
        variant_id=item.variant_id,
        sku=item.sku,
        name=item.name,
        quantity=item.quantity,
        unit_price_minor=item.unit_price_minor,
        line_total_minor=item.line_total_minor,
        commission_bps=item.commission_bps,
        commission_minor=item.commission_minor,
        payable_minor=item.payable_minor,
        status=item.status,
        order_number=order.order_number if order else None,
        order_status=order.status if order else None,
        payment_status=order.payment_status if order else None,
        settlement_id=item.settlement_id,
        metadata=item.metadata_json,
        created_at=item.created_at,
        updated_at=item.updated_at,
    )


def vendor_settlement_out(settlement: VendorSettlement) -> VendorSettlementOut:
    return VendorSettlementOut(
        id=settlement.id,
        company_id=settlement.company_id,
        vendor_id=settlement.vendor_id,
        settlement_number=settlement.settlement_number,
        currency=settlement.currency,
        period_start_at=settlement.period_start_at,
        period_end_at=settlement.period_end_at,
        status=settlement.status,
        gross_minor=settlement.gross_minor,
        commission_minor=settlement.commission_minor,
        payable_minor=settlement.payable_minor,
        paid_minor=settlement.paid_minor,
        payment_reference=settlement.payment_reference,
        journal_entry_id=settlement.journal_entry_id,
        paid_at=settlement.paid_at,
        metadata=settlement.metadata_json,
        created_at=settlement.created_at,
        updated_at=settlement.updated_at,
    )


def vendor_notification_out(notification: VendorNotification) -> VendorNotificationOut:
    return VendorNotificationOut(
        id=notification.id,
        company_id=notification.company_id,
        vendor_id=notification.vendor_id,
        channel=notification.channel,
        notification_type=notification.notification_type,
        subject=notification.subject,
        body=notification.body,
        status=notification.status,
        metadata=notification.metadata_json,
        created_at=notification.created_at,
        updated_at=notification.updated_at,
    )


def commission_rule_out(rule: MarketplaceCommissionRule) -> CommissionRuleOut:
    return CommissionRuleOut(
        id=rule.id,
        company_id=rule.company_id,
        name=rule.name,
        vendor_id=rule.vendor_id,
        category_id=rule.category_id,
        product_id=rule.product_id,
        commission_bps=rule.commission_bps,
        is_active=rule.is_active,
        metadata=rule.metadata_json,
        created_at=rule.created_at,
        updated_at=rule.updated_at,
    )


def list_vendors(
    db: Session,
    company_id: str | None,
    *,
    status: str | None = None,
) -> list[Vendor]:
    scoped_company_id = require_company_id(company_id)
    query = select(Vendor).where(Vendor.company_id == scoped_company_id)
    if status:
        normalized = normalize_vendor_status(status)
        query = query.where(func.lower(Vendor.status).in_(VENDOR_STATUS_STORAGE_VALUES[normalized]))
    return list(db.scalars(query.order_by(Vendor.name)).all())


def get_vendor(db: Session, company_id: str | None, vendor_id: str) -> Vendor:
    scoped_company_id = require_company_id(company_id)
    vendor = db.scalar(
        select(Vendor).where(Vendor.company_id == scoped_company_id, Vendor.id == vendor_id)
    )
    if vendor is None:
        raise ServiceError(404, "Vendor not found.")
    return vendor


def create_vendor(
    db: Session,
    *,
    company_id: str | None,
    user_id: str,
    payload: VendorCreate,
) -> Vendor:
    scoped_company_id = require_company_id(company_id)
    slug = normalize_vendor_slug(payload.name, payload.slug)
    if db.scalar(
        select(Vendor.id).where(Vendor.company_id == scoped_company_id, Vendor.slug == slug)
    ):
        raise ServiceError(409, f"Vendor slug already exists: {slug}.")
    vendor = Vendor(
        company_id=scoped_company_id,
        name=payload.name,
        slug=slug,
        legal_name=payload.legal_name,
        contact_name=payload.contact_name,
        email=payload.email,
        phone=payload.phone,
        status=normalize_vendor_status(payload.status),
        default_commission_bps=payload.default_commission_bps,
        metadata_json=payload.metadata,
    )
    db.add(vendor)
    db.flush()
    db.refresh(vendor)
    record_audit(
        db,
        action="marketplace.vendor_created",
        company_id=scoped_company_id,
        user_id=user_id,
        entity_type="vendor",
        entity_id=vendor.id,
        metadata={"name": vendor.name, "slug": vendor.slug},
    )
    return vendor


def update_vendor(
    db: Session,
    *,
    company_id: str | None,
    user_id: str,
    vendor_id: str,
    payload: VendorUpdate,
) -> Vendor:
    vendor = get_vendor(db, company_id, vendor_id)
    fields = payload.model_dump(exclude_unset=True)
    if "slug" in fields:
        vendor.slug = normalize_vendor_slug(fields.get("name") or vendor.name, fields["slug"])
        if db.scalar(
            select(Vendor.id).where(
                Vendor.company_id == vendor.company_id,
                Vendor.slug == vendor.slug,
                Vendor.id != vendor.id,
            )
        ):
            raise ServiceError(409, f"Vendor slug already exists: {vendor.slug}.")
    if "status" in fields and fields["status"] is not None:
        fields["status"] = normalize_vendor_status(fields["status"])
        change_vendor_status(
            db,
            company_id=vendor.company_id,
            actor_user_id=user_id,
            vendor_id=vendor.id,
            status=fields.pop("status"),
            reason="Vendor profile update",
        )
    for field in (
        "name",
        "legal_name",
        "contact_name",
        "email",
        "phone",
        "status",
        "default_commission_bps",
    ):
        if field in fields:
            setattr(vendor, field, fields[field])
    if "metadata" in fields:
        vendor.metadata_json = fields["metadata"]
    db.flush()
    db.refresh(vendor)
    record_audit(
        db,
        action="marketplace.vendor_updated",
        company_id=vendor.company_id,
        user_id=user_id,
        entity_type="vendor",
        entity_id=vendor.id,
        metadata={"name": vendor.name, "status": vendor.status},
    )
    return vendor


def approve_vendor(
    db: Session,
    *,
    company_id: str | None,
    user_id: str,
    vendor_id: str,
) -> Vendor:
    vendor = get_vendor(db, company_id, vendor_id)
    return change_vendor_status(
        db,
        company_id=vendor.company_id,
        actor_user_id=user_id,
        vendor_id=vendor.id,
        status="active",
        reason="Administrator approval",
    )


def list_vendor_users(db: Session, company_id: str | None, vendor_id: str) -> list[VendorUser]:
    vendor = get_vendor(db, company_id, vendor_id)
    scoped_company_id = vendor.company_id
    query = select(VendorUser).where(
        VendorUser.company_id == scoped_company_id,
        VendorUser.vendor_id == vendor.id,
    )
    return list(db.scalars(query.order_by(VendorUser.created_at)).all())


def add_vendor_user(
    db: Session,
    *,
    company_id: str | None,
    user_id: str,
    vendor_id: str,
    payload: VendorUserCreate,
) -> VendorUser:
    vendor = get_vendor(db, company_id, vendor_id)
    scoped_company_id = vendor.company_id
    linked_user = db.scalar(
        select(User).where(User.company_id == scoped_company_id, User.id == payload.user_id)
    )
    if linked_user is None:
        raise ServiceError(404, "User not found for this company.")
    if db.scalar(
        select(VendorUser.id).where(
            VendorUser.company_id == scoped_company_id,
            VendorUser.vendor_id == vendor.id,
            VendorUser.user_id == payload.user_id,
        )
    ):
        raise ServiceError(409, "User is already linked to this vendor.")
    vendor_user = VendorUser(
        company_id=scoped_company_id,
        vendor_id=vendor.id,
        user_id=linked_user.id,
        role_name=payload.role_name,
        is_primary=payload.is_primary,
        metadata_json=payload.metadata,
    )
    db.add(vendor_user)
    if payload.role_name.strip().lower() == "vendor":
        from erp.packages.core.vendor_auth_services import ensure_vendor_role

        role = ensure_vendor_role(db, scoped_company_id)
        if not db.scalar(
            select(UserRole.user_id).where(
                UserRole.user_id == linked_user.id, UserRole.role_id == role.id
            )
        ):
            db.add(UserRole(user_id=linked_user.id, role_id=role.id))
    db.flush()
    db.refresh(vendor_user)
    record_audit(
        db,
        action="marketplace.vendor_user_linked",
        company_id=scoped_company_id,
        user_id=user_id,
        entity_type="vendor_user",
        entity_id=vendor_user.id,
        metadata={"vendor_id": vendor.id, "user_id": linked_user.id},
    )
    return vendor_user


def vendor_for_user(db: Session, company_id: str, user_id: str) -> Vendor:
    links = list(
        db.scalars(
            select(VendorUser).where(
                VendorUser.company_id == company_id,
                VendorUser.user_id == user_id,
                func.lower(VendorUser.role_name) == "vendor",
            )
        ).all()
    )
    primary_links = [link for link in links if link.is_primary]
    if len(primary_links) > 1 or (not primary_links and len(links) > 1):
        raise ServiceError(409, "Vendor account relationship is ambiguous.")
    if len(primary_links) != 1:
        raise ServiceError(404, "Vendor profile not found for the current user.")
    link = primary_links[0]
    vendor = db.scalar(
        select(Vendor).where(
            Vendor.company_id == company_id,
            Vendor.id == link.vendor_id,
        )
    )
    if vendor is None:
        raise ServiceError(404, "Vendor profile not found for the current user.")
    if normalize_vendor_status(vendor.status) != "active":
        raise ServiceError(403, "Vendor account is not active.")
    return vendor


def resolve_vendor_for_product(db: Session, company_id: str, product: Product) -> Vendor | None:
    if product.vendor_id:
        return db.scalar(
            select(Vendor).where(Vendor.company_id == company_id, Vendor.id == product.vendor_id)
        )
    mapping = db.scalar(
        select(VendorProduct).where(
            VendorProduct.company_id == company_id,
            VendorProduct.product_id == product.id,
        )
    )
    if mapping:
        return db.scalar(
            select(Vendor).where(Vendor.company_id == company_id, Vendor.id == mapping.vendor_id)
        )
    return None


def list_vendor_products(
    db: Session,
    company_id: str | None,
    *,
    vendor_id: str | None = None,
) -> list[VendorProduct]:
    scoped_company_id = require_company_id(company_id)
    query = select(VendorProduct).where(VendorProduct.company_id == scoped_company_id)
    if vendor_id:
        query = query.where(VendorProduct.vendor_id == vendor_id)
    return list(db.scalars(query.order_by(VendorProduct.created_at.desc())).all())


def vendor_owned_product(db: Session, company_id: str, vendor_id: str, product_id: str) -> Product:
    product = db.scalar(
        select(Product).where(
            Product.company_id == company_id,
            Product.id == product_id,
            Product.vendor_id == vendor_id,
        )
    )
    if product is None:
        raise ServiceError(404, "Vendor product not found.")
    return product


def create_vendor_product(
    db: Session,
    *,
    company_id: str,
    user_id: str,
    vendor_id: str,
    payload,
) -> Product:
    """Create a product owned by the authenticated vendor."""
    from erp.packages.core.catalog_services import create_product

    # Vendor ownership is always server-controlled, while the remaining product
    # fields are intentionally preserved so the web editor matches the desktop ERP.
    vendor_payload = payload.model_copy(update={"vendor_id": vendor_id})
    product = create_product(db, company_id=company_id, user_id=user_id, payload=vendor_payload)
    assignment = VendorProduct(
        company_id=company_id,
        vendor_id=vendor_id,
        product_id=product.id,
        ownership_type="vendor_owned",
        approval_status="published",
        published_at=utcnow(),
        metadata_json={"self_service": True},
    )
    db.add(assignment)
    record_audit(
        db,
        action="marketplace.vendor_product_created",
        company_id=company_id,
        user_id=user_id,
        entity_type="product",
        entity_id=product.id,
        metadata={"vendor_id": vendor_id, "published": True},
    )
    db.flush()
    return product


def update_vendor_product(
    db: Session,
    *,
    company_id: str,
    user_id: str,
    vendor_id: str,
    product_id: str,
    payload,
) -> Product:
    from erp.packages.core.catalog_services import update_product

    vendor_owned_product(db, company_id, vendor_id, product_id)
    fields = payload.model_dump(exclude_unset=True)
    fields.pop("vendor_id", None)
    product = update_product(
        db,
        company_id=company_id,
        user_id=user_id,
        product_id=product_id,
        payload=payload.__class__(**fields),
    )
    assignment = db.scalar(
        select(VendorProduct).where(
            VendorProduct.company_id == company_id,
            VendorProduct.vendor_id == vendor_id,
            VendorProduct.product_id == product_id,
        )
    )
    if assignment and product.status == "active":
        assignment.approval_status = "published"
        assignment.published_at = utcnow()
    record_audit(
        db,
        action="marketplace.vendor_product_updated",
        company_id=company_id,
        user_id=user_id,
        entity_type="product",
        entity_id=product.id,
        metadata={"vendor_id": vendor_id},
    )
    db.flush()
    return product


def change_vendor_order_item_status(
    db: Session,
    *,
    company_id: str,
    user_id: str,
    vendor_id: str,
    vendor_order_item_id: str,
    payload: VendorOrderItemStatusChange,
) -> VendorOrderItem:
    item = db.scalar(
        select(VendorOrderItem).where(
            VendorOrderItem.company_id == company_id,
            VendorOrderItem.vendor_id == vendor_id,
            VendorOrderItem.id == vendor_order_item_id,
        )
    )
    if item is None:
        raise ServiceError(404, "Vendor order item not found.")
    target = payload.status
    current = item.status.strip().lower()
    if target == "rejected" and not (payload.reason or "").strip():
        raise ServiceError(422, "A rejection reason is required.")
    if target not in VENDOR_ORDER_ITEM_TRANSITIONS.get(current, set()):
        raise ServiceError(409, f"Cannot transition vendor item from {current} to {target}.")
    item.status = target
    history = VendorOrderItemStatusHistory(
        company_id=company_id,
        vendor_order_item_id=item.id,
        vendor_id=vendor_id,
        from_status=current,
        to_status=target,
        changed_by_id=user_id,
        reason=payload.reason.strip() if payload.reason else None,
    )
    db.add(history)
    record_audit(
        db,
        action="marketplace.vendor_order_item_status_changed",
        company_id=company_id,
        user_id=user_id,
        entity_type="vendor_order_item",
        entity_id=item.id,
        metadata={"vendor_id": vendor_id, "from_status": current, "to_status": target},
    )
    db.flush()
    from erp.packages.core.push_services import enqueue_vendor_item_status_changed

    enqueue_vendor_item_status_changed(
        db,
        company_id=company_id,
        order_id=item.order_id,
        vendor_id=vendor_id,
        history_id=history.id,
        from_status=current,
        to_status=target,
    )
    return item


def vendor_order_item_status_history(
    db: Session, company_id: str, vendor_id: str, vendor_order_item_id: str
) -> list[VendorOrderItemStatusHistory]:
    return list(
        db.scalars(
            select(VendorOrderItemStatusHistory)
            .where(
                VendorOrderItemStatusHistory.company_id == company_id,
                VendorOrderItemStatusHistory.vendor_id == vendor_id,
                VendorOrderItemStatusHistory.vendor_order_item_id == vendor_order_item_id,
            )
            .order_by(VendorOrderItemStatusHistory.created_at, VendorOrderItemStatusHistory.id)
        ).all()
    )


def assign_product_to_vendor(
    db: Session,
    *,
    company_id: str | None,
    user_id: str,
    payload: VendorProductAssignRequest,
) -> VendorProduct:
    scoped_company_id = require_company_id(company_id)
    vendor = get_vendor(db, scoped_company_id, payload.vendor_id) if payload.vendor_id else None
    if vendor is None:
        raise ServiceError(422, "A vendor_id is required to assign a product.")
    product = db.scalar(
        select(Product).where(
            Product.company_id == scoped_company_id,
            Product.id == payload.product_id,
        )
    )
    if product is None:
        raise ServiceError(404, "Product not found.")
    existing = db.scalar(
        select(VendorProduct).where(
            VendorProduct.company_id == scoped_company_id,
            VendorProduct.product_id == product.id,
        )
    )
    if existing is None:
        existing = VendorProduct(
            company_id=scoped_company_id,
            vendor_id=vendor.id,
            product_id=product.id,
            approval_status=normalize_vendor_product_status(payload.approval_status),
            ownership_type=payload.ownership_type,
            metadata_json=payload.metadata,
        )
        db.add(existing)
    else:
        existing.vendor_id = vendor.id
        existing.approval_status = normalize_vendor_product_status(payload.approval_status)
        existing.ownership_type = payload.ownership_type
        existing.metadata_json = payload.metadata
    product.vendor_id = vendor.id
    if product.status == "active" and existing.approval_status == "submitted":
        product.status = "draft"
    db.flush()
    db.refresh(existing)
    record_audit(
        db,
        action="marketplace.product_assigned",
        company_id=scoped_company_id,
        user_id=user_id,
        entity_type="vendor_product",
        entity_id=existing.id,
        metadata={"vendor_id": vendor.id, "product_id": product.id},
    )
    return existing


def approve_vendor_product(
    db: Session,
    *,
    company_id: str | None,
    user_id: str,
    vendor_id: str,
    product_id: str,
) -> VendorProduct:
    scoped_company_id = require_company_id(company_id)
    vendor_product = db.scalar(
        select(VendorProduct).where(
            VendorProduct.company_id == scoped_company_id,
            VendorProduct.vendor_id == vendor_id,
            VendorProduct.product_id == product_id,
        )
    )
    if vendor_product is None:
        raise ServiceError(404, "Vendor product assignment not found.")
    vendor_product.approval_status = "approved"
    vendor_product.approved_by_id = user_id
    vendor_product.approved_at = utcnow()
    product = db.scalar(
        select(Product).where(
            Product.company_id == scoped_company_id,
            Product.id == product_id,
        )
    )
    if product:
        product.vendor_id = vendor_id
        product.status = "active"
    db.flush()
    db.refresh(vendor_product)
    record_audit(
        db,
        action="marketplace.product_approved",
        company_id=scoped_company_id,
        user_id=user_id,
        entity_type="vendor_product",
        entity_id=vendor_product.id,
        metadata={"product_id": product_id, "vendor_id": vendor_id},
    )
    return vendor_product


def list_commission_rules(
    db: Session,
    company_id: str | None,
    *,
    vendor_id: str | None = None,
) -> list[MarketplaceCommissionRule]:
    scoped_company_id = require_company_id(company_id)
    query = select(MarketplaceCommissionRule).where(
        MarketplaceCommissionRule.company_id == scoped_company_id
    )
    if vendor_id:
        query = query.where(MarketplaceCommissionRule.vendor_id == vendor_id)
    return list(db.scalars(query.order_by(MarketplaceCommissionRule.updated_at.desc())).all())


def create_commission_rule(
    db: Session,
    *,
    company_id: str | None,
    user_id: str,
    payload: CommissionRuleCreate,
) -> MarketplaceCommissionRule:
    scoped_company_id = require_company_id(company_id)
    rule = MarketplaceCommissionRule(
        company_id=scoped_company_id,
        name=payload.name,
        vendor_id=payload.vendor_id,
        category_id=payload.category_id,
        product_id=payload.product_id,
        commission_bps=payload.commission_bps,
        is_active=payload.is_active,
        metadata_json=payload.metadata,
    )
    db.add(rule)
    db.flush()
    db.refresh(rule)
    record_audit(
        db,
        action="marketplace.commission_rule_created",
        company_id=scoped_company_id,
        user_id=user_id,
        entity_type="commission_rule",
        entity_id=rule.id,
        metadata={"name": rule.name, "commission_bps": rule.commission_bps},
    )
    return rule


def update_commission_rule(
    db: Session,
    *,
    company_id: str | None,
    user_id: str,
    rule_id: str,
    payload: CommissionRuleUpdate,
) -> MarketplaceCommissionRule:
    scoped_company_id = require_company_id(company_id)
    rule = db.scalar(
        select(MarketplaceCommissionRule).where(
            MarketplaceCommissionRule.company_id == scoped_company_id,
            MarketplaceCommissionRule.id == rule_id,
        )
    )
    if rule is None:
        raise ServiceError(404, "Commission rule not found.")
    fields = payload.model_dump(exclude_unset=True)
    for field in ("name", "vendor_id", "category_id", "product_id", "commission_bps", "is_active"):
        if field in fields:
            setattr(rule, field, fields[field])
    if "metadata" in fields:
        rule.metadata_json = fields["metadata"]
    db.flush()
    db.refresh(rule)
    record_audit(
        db,
        action="marketplace.commission_rule_updated",
        company_id=scoped_company_id,
        user_id=user_id,
        entity_type="commission_rule",
        entity_id=rule.id,
        metadata={"name": rule.name, "commission_bps": rule.commission_bps},
    )
    return rule


def commission_rule_for_product(
    db: Session,
    *,
    company_id: str,
    product: Product,
    vendor: Vendor | None,
) -> MarketplaceCommissionRule | None:
    rules = list(
        db.scalars(
            select(MarketplaceCommissionRule).where(
                MarketplaceCommissionRule.company_id == company_id,
                MarketplaceCommissionRule.is_active.is_(True),
            )
        ).all()
    )
    best_rule: MarketplaceCommissionRule | None = None
    best_score = -1
    for rule in rules:
        if rule.product_id == product.id and rule.vendor_id == (vendor.id if vendor else None):
            score = 5
        elif rule.product_id == product.id and rule.vendor_id is None:
            score = 4
        elif rule.category_id == product.category_id and rule.vendor_id == (
            vendor.id if vendor else None
        ):
            score = 3
        elif rule.category_id == product.category_id and rule.vendor_id is None:
            score = 2
        elif rule.vendor_id == (vendor.id if vendor else None):
            score = 1
        elif rule.vendor_id is None and rule.category_id is None and rule.product_id is None:
            score = 0
        else:
            continue
        if score > best_score:
            best_rule = rule
            best_score = score
    return best_rule


def resolve_commission_bps(
    db: Session,
    *,
    company_id: str,
    product: Product,
    vendor: Vendor | None,
) -> int:
    rule = commission_rule_for_product(db, company_id=company_id, product=product, vendor=vendor)
    if rule:
        return rule.commission_bps
    if vendor:
        return vendor.default_commission_bps
    return 0


def record_vendor_order_item(
    db: Session,
    *,
    company_id: str,
    order: Order,
    order_item: OrderItem,
    product: Product,
    vendor: Vendor | None,
    variant: ProductVariant | None,
    source_metadata: dict[str, Any] | None = None,
) -> VendorOrderItem | None:
    if vendor is None:
        vendor = resolve_vendor_for_product(db, company_id, product)
    if vendor is None:
        return None
    order_item.vendor_id = vendor.id

    commission_bps = resolve_commission_bps(
        db,
        company_id=company_id,
        product=product,
        vendor=vendor,
    )
    commission_minor = int(round(order_item.line_total_minor * commission_bps / 10000))
    payable_minor = max(order_item.line_total_minor - commission_minor, 0)
    existing = db.scalar(
        select(VendorOrderItem).where(
            VendorOrderItem.company_id == company_id,
            VendorOrderItem.order_item_id == order_item.id,
        )
    )
    if existing is None:
        existing = VendorOrderItem(
            company_id=company_id,
            vendor_id=vendor.id,
            order_id=order.id,
            order_item_id=order_item.id,
            product_id=product.id,
            variant_id=variant.id if variant else order_item.variant_id,
            sku=order_item.sku,
            name=order_item.name,
            quantity=order_item.quantity,
            unit_price_minor=order_item.unit_price_minor,
            line_total_minor=order_item.line_total_minor,
            commission_bps=commission_bps,
            commission_minor=commission_minor,
            payable_minor=payable_minor,
            status="pending",
            metadata_json=source_metadata or {},
        )
        db.add(existing)
    else:
        existing.vendor_id = vendor.id
        existing.order_id = order.id
        existing.product_id = product.id
        existing.variant_id = variant.id if variant else order_item.variant_id
        existing.sku = order_item.sku
        existing.name = order_item.name
        existing.quantity = order_item.quantity
        existing.unit_price_minor = order_item.unit_price_minor
        existing.line_total_minor = order_item.line_total_minor
        existing.commission_bps = commission_bps
        existing.commission_minor = commission_minor
        existing.payable_minor = payable_minor
        if source_metadata is not None:
            existing.metadata_json = source_metadata
    db.flush()
    return existing


def record_vendor_order_items_for_order(
    db: Session,
    *,
    company_id: str,
    order: Order,
) -> list[VendorOrderItem]:
    rows = list(
        db.scalars(
            select(OrderItem).where(
                OrderItem.company_id == company_id,
                OrderItem.order_id == order.id,
            )
        ).all()
    )
    created: list[VendorOrderItem] = []
    for item in rows:
        product = db.scalar(
            select(Product).where(
                Product.company_id == company_id,
                Product.id == item.product_id,
            )
        )
        if product is None:
            continue
        variant = None
        if item.variant_id:
            variant = db.scalar(
                select(ProductVariant).where(
                    ProductVariant.company_id == company_id,
                    ProductVariant.id == item.variant_id,
                )
            )
        vendor = resolve_vendor_for_product(db, company_id, product)
        vendor_item = record_vendor_order_item(
            db,
            company_id=company_id,
            order=order,
            order_item=item,
            product=product,
            vendor=vendor,
            variant=variant,
            source_metadata=item.metadata_json,
        )
        if vendor_item is not None:
            created.append(vendor_item)
    return created


def list_vendor_order_items(
    db: Session,
    company_id: str | None,
    *,
    vendor_id: str | None = None,
    status: str | None = None,
    order_status: str | None = None,
    payment_status: str | None = None,
    settlement_id: str | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    offset: int = 0,
    limit: int = 100,
) -> list[VendorOrderItem]:
    scoped_company_id = require_company_id(company_id)
    date_from = to_utc(date_from)
    date_to = to_utc(date_to)
    if date_from and date_to and date_from > date_to:
        raise ServiceError(422, "date_from must not be later than date_to.")
    query = select(VendorOrderItem).where(VendorOrderItem.company_id == scoped_company_id)
    if vendor_id:
        query = query.where(VendorOrderItem.vendor_id == vendor_id)
    if status:
        query = query.where(VendorOrderItem.status == status)
    if settlement_id:
        query = query.where(VendorOrderItem.settlement_id == settlement_id)
    if order_status or payment_status:
        query = query.join(
            Order,
            (Order.id == VendorOrderItem.order_id)
            & (Order.company_id == VendorOrderItem.company_id),
        )
    if order_status:
        query = query.where(Order.status == order_status)
    if payment_status:
        query = query.where(Order.payment_status == payment_status)
    if date_from:
        query = query.where(VendorOrderItem.created_at >= date_from)
    if date_to:
        query = query.where(VendorOrderItem.created_at <= date_to)
    return list(
        db.scalars(
            query.order_by(VendorOrderItem.created_at.desc(), VendorOrderItem.id.desc())
            .offset(max(0, offset))
            .limit(max(1, min(limit, 500)))
        ).all()
    )


def list_vendor_settlements(
    db: Session,
    company_id: str | None,
    *,
    vendor_id: str | None = None,
    status: str | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    offset: int = 0,
    limit: int = 100,
) -> list[VendorSettlement]:
    scoped_company_id = require_company_id(company_id)
    date_from = to_utc(date_from)
    date_to = to_utc(date_to)
    if date_from and date_to and date_from > date_to:
        raise ServiceError(422, "date_from must not be later than date_to.")
    query = select(VendorSettlement).where(VendorSettlement.company_id == scoped_company_id)
    if vendor_id:
        query = query.where(VendorSettlement.vendor_id == vendor_id)
    if status:
        query = query.where(VendorSettlement.status == status)
    if date_from:
        query = query.where(VendorSettlement.created_at >= date_from)
    if date_to:
        query = query.where(VendorSettlement.created_at <= date_to)
    return list(
        db.scalars(
            query.order_by(VendorSettlement.created_at.desc(), VendorSettlement.id.desc())
            .offset(max(0, offset))
            .limit(max(1, min(limit, 500)))
        ).all()
    )


def create_vendor_settlement(
    db: Session,
    *,
    company_id: str | None,
    user_id: str,
    payload: VendorSettlementCreate,
) -> VendorSettlement:
    scoped_company_id = require_company_id(company_id)
    if payload.vendor_id is None:
        raise ServiceError(422, "A vendor_id is required to create a settlement.")
    vendor = get_vendor(db, scoped_company_id, payload.vendor_id)
    query = select(VendorOrderItem).where(
        VendorOrderItem.company_id == scoped_company_id,
        VendorOrderItem.vendor_id == vendor.id,
        VendorOrderItem.settlement_id.is_(None),
    )
    if payload.period_start_at is not None:
        query = query.where(VendorOrderItem.created_at >= payload.period_start_at)
    if payload.period_end_at is not None:
        query = query.where(VendorOrderItem.created_at <= payload.period_end_at)
    items = list(db.scalars(query.order_by(VendorOrderItem.created_at)).all())
    if not items:
        raise ServiceError(409, "No unsettled vendor items were found for the requested period.")

    gross_minor = sum(item.line_total_minor for item in items)
    commission_minor = sum(item.commission_minor for item in items)
    payable_minor = sum(item.payable_minor for item in items)
    settlement = VendorSettlement(
        company_id=scoped_company_id,
        vendor_id=vendor.id,
        settlement_number=payload.settlement_number or generate_entry_number("VSET"),
        currency=payload.currency,
        period_start_at=payload.period_start_at,
        period_end_at=payload.period_end_at,
        status="draft",
        gross_minor=gross_minor,
        commission_minor=commission_minor,
        payable_minor=payable_minor,
        paid_minor=0,
        payment_reference=payload.payment_reference,
        metadata_json=payload.metadata,
    )
    db.add(settlement)
    db.flush()

    for item in items:
        item.settlement_id = settlement.id
        item.status = "allocated"
    db.flush()

    post_vendor_settlement_entry(
        db,
        company_id=scoped_company_id,
        user_id=user_id,
        settlement=settlement,
    )
    db.refresh(settlement)
    record_audit(
        db,
        action="marketplace.settlement_posted",
        company_id=scoped_company_id,
        user_id=user_id,
        entity_type="vendor_settlement",
        entity_id=settlement.id,
        metadata={"vendor_id": vendor.id, "payable_minor": settlement.payable_minor},
    )
    return settlement


def vendor_dashboard_summary(db: Session, company_id: str | None, vendor_id: str) -> dict[str, Any]:
    scoped_company_id = require_company_id(company_id)
    product_count = (
        db.scalar(
            select(func.count(Product.id)).where(
                Product.company_id == scoped_company_id,
                Product.vendor_id == vendor_id,
                Product.status != "archived",
            )
        )
        or 0
    )
    pending_products = (
        db.scalar(
            select(func.count(VendorProduct.id)).where(
                VendorProduct.company_id == scoped_company_id,
                VendorProduct.vendor_id == vendor_id,
                VendorProduct.approval_status != "approved",
            )
        )
        or 0
    )
    order_count = (
        db.scalar(
            select(func.count(VendorOrderItem.id)).where(
                VendorOrderItem.company_id == scoped_company_id,
                VendorOrderItem.vendor_id == vendor_id,
            )
        )
        or 0
    )
    settlement_count = (
        db.scalar(
            select(func.count(VendorSettlement.id)).where(
                VendorSettlement.company_id == scoped_company_id,
                VendorSettlement.vendor_id == vendor_id,
            )
        )
        or 0
    )
    balance_minor = vendor_balance_minor(db, scoped_company_id, vendor_id)
    return {
        "vendor_id": vendor_id,
        "product_count": int(product_count),
        "pending_products": int(pending_products),
        "order_count": int(order_count),
        "settlement_count": int(settlement_count),
        "balance_minor": int(balance_minor),
    }


def list_vendor_notifications(
    db: Session,
    company_id: str | None,
    *,
    vendor_id: str | None = None,
) -> list[VendorNotification]:
    scoped_company_id = require_company_id(company_id)
    query = select(VendorNotification).where(VendorNotification.company_id == scoped_company_id)
    if vendor_id:
        query = query.where(VendorNotification.vendor_id == vendor_id)
    return list(db.scalars(query.order_by(VendorNotification.created_at.desc())).all())
