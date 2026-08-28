from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from erp.packages.core.catalog_services import require_company_id
from erp.packages.core.db.models import (
    Customer,
    CustomerAddress,
    CustomerNote,
    CustomerTag,
)
from erp.packages.core.schemas import (
    CustomerAddressCreate,
    CustomerCreate,
    CustomerNoteCreate,
    CustomerUpdate,
)
from erp.packages.core.services import ServiceError, record_audit

CUSTOMER_STATUSES = {"active", "inactive", "archived"}


def normalize_customer_status(status: str) -> str:
    normalized = status.lower()
    if normalized not in CUSTOMER_STATUSES:
        raise ServiceError(422, f"Unsupported customer status: {status}.")
    return normalized


def normalize_tag(tag: str) -> str:
    normalized = tag.strip().lower()
    if not normalized or len(normalized) > 80:
        raise ServiceError(422, "Customer tags must be between 1 and 80 characters.")
    return normalized


def ensure_customer_contact_unique(
    db: Session,
    *,
    company_id: str,
    email: str | None,
    phone: str | None,
    exclude_customer_id: str | None = None,
) -> None:
    if email:
        query = select(Customer.id).where(
            Customer.company_id == company_id,
            Customer.email == email,
        )
        if exclude_customer_id:
            query = query.where(Customer.id != exclude_customer_id)
        if db.scalar(query):
            raise ServiceError(409, f"Customer email already exists: {email}.")
    if phone:
        query = select(Customer.id).where(
            Customer.company_id == company_id,
            Customer.phone == phone,
        )
        if exclude_customer_id:
            query = query.where(Customer.id != exclude_customer_id)
        if db.scalar(query):
            raise ServiceError(409, f"Customer phone already exists: {phone}.")


def customer_addresses(db: Session, customer_id: str) -> list[CustomerAddress]:
    return list(
        db.scalars(
            select(CustomerAddress)
            .where(CustomerAddress.customer_id == customer_id)
            .order_by(CustomerAddress.is_default.desc(), CustomerAddress.created_at)
        ).all()
    )


def customer_notes(db: Session, customer_id: str) -> list[CustomerNote]:
    return list(
        db.scalars(
            select(CustomerNote)
            .where(CustomerNote.customer_id == customer_id)
            .order_by(CustomerNote.created_at.desc())
        ).all()
    )


def customer_tags(db: Session, customer_id: str) -> list[str]:
    return list(
        db.scalars(
            select(CustomerTag.tag)
            .where(CustomerTag.customer_id == customer_id)
            .order_by(CustomerTag.tag)
        ).all()
    )


def replace_customer_tags(
    db: Session,
    *,
    company_id: str,
    customer_id: str,
    tags: list[str],
) -> None:
    for existing in db.scalars(select(CustomerTag).where(CustomerTag.customer_id == customer_id)):
        db.delete(existing)
    for tag in sorted({normalize_tag(tag) for tag in tags}):
        db.add(CustomerTag(company_id=company_id, customer_id=customer_id, tag=tag))


def list_customers(
    db: Session,
    company_id: str | None,
    *,
    include_archived: bool = False,
) -> list[Customer]:
    scoped_company_id = require_company_id(company_id)
    query = select(Customer).where(Customer.company_id == scoped_company_id)
    if not include_archived:
        query = query.where(Customer.status != "archived")
    return list(db.scalars(query.order_by(Customer.full_name)).all())


def get_customer(db: Session, company_id: str | None, customer_id: str) -> Customer:
    scoped_company_id = require_company_id(company_id)
    customer = db.scalar(
        select(Customer).where(Customer.company_id == scoped_company_id, Customer.id == customer_id)
    )
    if customer is None:
        raise ServiceError(404, "Customer not found.")
    return customer


def create_customer(
    db: Session,
    *,
    company_id: str | None,
    user_id: str,
    payload: CustomerCreate,
) -> Customer:
    scoped_company_id = require_company_id(company_id)
    ensure_customer_contact_unique(
        db,
        company_id=scoped_company_id,
        email=payload.email,
        phone=payload.phone,
    )
    customer = Customer(
        company_id=scoped_company_id,
        full_name=payload.full_name,
        source_channel=payload.source_channel,
        email=payload.email,
        phone=payload.phone,
        status=normalize_customer_status(payload.status),
        credit_limit_minor=payload.credit_limit_minor,
        metadata_json=payload.metadata,
    )
    db.add(customer)
    db.flush()
    for address_payload in payload.addresses:
        db.add(
            CustomerAddress(
                company_id=scoped_company_id,
                customer_id=customer.id,
                label=address_payload.label,
                recipient_name=address_payload.recipient_name,
                phone=address_payload.phone,
                line1=address_payload.line1,
                line2=address_payload.line2,
                city=address_payload.city,
                state=address_payload.state,
                postal_code=address_payload.postal_code,
                country=address_payload.country.upper(),
                is_default=address_payload.is_default,
            )
        )
    replace_customer_tags(
        db,
        company_id=scoped_company_id,
        customer_id=customer.id,
        tags=payload.tags,
    )
    if payload.opening_note:
        db.add(
            CustomerNote(
                company_id=scoped_company_id,
                customer_id=customer.id,
                created_by_id=user_id,
                note=payload.opening_note,
            )
        )
    db.flush()
    db.refresh(customer)
    record_audit(
        db,
        action="customers.customer_created",
        company_id=scoped_company_id,
        user_id=user_id,
        entity_type="customer",
        entity_id=customer.id,
        metadata={"full_name": customer.full_name},
    )
    return customer


def update_customer(
    db: Session,
    *,
    company_id: str | None,
    user_id: str,
    customer_id: str,
    payload: CustomerUpdate,
) -> Customer:
    scoped_company_id = require_company_id(company_id)
    customer = get_customer(db, scoped_company_id, customer_id)
    fields = payload.model_dump(exclude_unset=True)
    ensure_customer_contact_unique(
        db,
        company_id=scoped_company_id,
        email=fields.get("email", customer.email),
        phone=fields.get("phone", customer.phone),
        exclude_customer_id=customer.id,
    )
    if "status" in fields and fields["status"] is not None:
        fields["status"] = normalize_customer_status(fields["status"])
    for field in ("full_name", "email", "phone", "status", "credit_limit_minor"):
        if field in fields:
            setattr(customer, field, fields[field])
    if "metadata" in fields:
        customer.metadata_json = fields["metadata"]
    if "tags" in fields and fields["tags"] is not None:
        replace_customer_tags(
            db,
            company_id=scoped_company_id,
            customer_id=customer.id,
            tags=fields["tags"],
        )
    db.flush()
    db.refresh(customer)
    record_audit(
        db,
        action="customers.customer_updated",
        company_id=scoped_company_id,
        user_id=user_id,
        entity_type="customer",
        entity_id=customer.id,
        metadata={"updated_fields": sorted(fields)},
    )
    return customer


def archive_customer(
    db: Session,
    *,
    company_id: str | None,
    user_id: str,
    customer_id: str,
) -> None:
    scoped_company_id = require_company_id(company_id)
    customer = get_customer(db, scoped_company_id, customer_id)
    customer.status = "archived"
    record_audit(
        db,
        action="customers.customer_deleted",
        company_id=scoped_company_id,
        user_id=user_id,
        entity_type="customer",
        entity_id=customer.id,
        metadata={"soft_delete": True},
    )


def add_customer_address(
    db: Session,
    *,
    company_id: str | None,
    user_id: str,
    customer_id: str,
    payload: CustomerAddressCreate,
) -> CustomerAddress:
    scoped_company_id = require_company_id(company_id)
    customer = get_customer(db, scoped_company_id, customer_id)
    address = CustomerAddress(
        company_id=scoped_company_id,
        customer_id=customer.id,
        label=payload.label,
        recipient_name=payload.recipient_name,
        phone=payload.phone,
        line1=payload.line1,
        line2=payload.line2,
        city=payload.city,
        state=payload.state,
        postal_code=payload.postal_code,
        country=payload.country.upper(),
        is_default=payload.is_default,
    )
    db.add(address)
    db.flush()
    db.refresh(address)
    record_audit(
        db,
        action="customers.address_created",
        company_id=scoped_company_id,
        user_id=user_id,
        entity_type="customer_address",
        entity_id=address.id,
        metadata={"customer_id": customer.id},
    )
    return address


def add_customer_note(
    db: Session,
    *,
    company_id: str | None,
    user_id: str,
    customer_id: str,
    payload: CustomerNoteCreate,
) -> CustomerNote:
    scoped_company_id = require_company_id(company_id)
    customer = get_customer(db, scoped_company_id, customer_id)
    note = CustomerNote(
        company_id=scoped_company_id,
        customer_id=customer.id,
        created_by_id=user_id,
        note=payload.note,
    )
    db.add(note)
    db.flush()
    db.refresh(note)
    record_audit(
        db,
        action="customers.note_created",
        company_id=scoped_company_id,
        user_id=user_id,
        entity_type="customer_note",
        entity_id=note.id,
        metadata={"customer_id": customer.id},
    )
    return note
