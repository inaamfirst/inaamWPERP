from __future__ import annotations

import re
import string
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from erp.packages.core.catalog_services import require_company_id
from erp.packages.core.db.models import (
    NotificationDeliveryLog,
    NotificationQueue,
    NotificationTemplate,
)
from erp.packages.core.schemas import (
    WhatsAppMessageEnqueue,
    WhatsAppTemplateCreate,
)
from erp.packages.core.services import ServiceError, record_audit, utcnow

CHANNEL = "whatsapp"
PHONE_PATTERN = re.compile(r"^\+?[0-9][0-9\s().-]{7,78}$")


@dataclass(frozen=True)
class DeliveryResult:
    ok: bool
    status: str
    provider_message_id: str | None = None
    error: str | None = None
    payload: dict[str, object] | None = None


class MockWhatsAppAdapter:
    name = "mock-local"

    def __init__(self, *, force_failure: bool = False) -> None:
        self.force_failure = force_failure

    def send(self, message: NotificationQueue) -> DeliveryResult:
        if self.force_failure:
            return DeliveryResult(
                ok=False,
                status="failed",
                error="Mock WhatsApp adapter forced failure.",
                payload={"recipient_phone": message.recipient_phone},
            )
        return DeliveryResult(
            ok=True,
            status="sent",
            provider_message_id=f"mock-{message.id}",
            payload={"recipient_phone": message.recipient_phone},
        )


def normalize_phone(value: str) -> str:
    phone = value.strip()
    if not PHONE_PATTERN.fullmatch(phone):
        raise ServiceError(422, "Recipient phone number is invalid.")
    return phone


def list_templates(db: Session, company_id: str | None) -> list[NotificationTemplate]:
    scoped_company_id = require_company_id(company_id)
    return list(
        db.scalars(
            select(NotificationTemplate)
            .where(
                NotificationTemplate.company_id == scoped_company_id,
                NotificationTemplate.channel == CHANNEL,
            )
            .order_by(NotificationTemplate.name)
        ).all()
    )


def get_template(db: Session, company_id: str | None, template_id: str) -> NotificationTemplate:
    scoped_company_id = require_company_id(company_id)
    template = db.scalar(
        select(NotificationTemplate).where(
            NotificationTemplate.company_id == scoped_company_id,
            NotificationTemplate.channel == CHANNEL,
            NotificationTemplate.id == template_id,
        )
    )
    if template is None:
        raise ServiceError(404, "WhatsApp template not found.")
    if not template.is_active:
        raise ServiceError(409, "WhatsApp template is inactive.")
    return template


def create_template(
    db: Session,
    *,
    company_id: str | None,
    user_id: str,
    payload: WhatsAppTemplateCreate,
) -> NotificationTemplate:
    scoped_company_id = require_company_id(company_id)
    existing = db.scalar(
        select(NotificationTemplate.id).where(
            NotificationTemplate.company_id == scoped_company_id,
            NotificationTemplate.channel == CHANNEL,
            NotificationTemplate.name == payload.name,
        )
    )
    if existing:
        raise ServiceError(409, f"WhatsApp template already exists: {payload.name}.")
    template = NotificationTemplate(
        company_id=scoped_company_id,
        channel=CHANNEL,
        name=payload.name,
        language=payload.language,
        body=payload.body,
        is_active=True,
    )
    db.add(template)
    db.flush()
    db.refresh(template)
    record_audit(
        db,
        action="whatsapp.template_created",
        company_id=scoped_company_id,
        user_id=user_id,
        entity_type="notification_template",
        entity_id=template.id,
        metadata={"name": template.name},
    )
    return template


def render_template(body: str, variables: dict[str, object]) -> str:
    formatter = string.Formatter()
    required_fields = {
        field_name
        for _literal, field_name, _format_spec, _conversion in formatter.parse(body)
        if field_name
    }
    missing = sorted(field for field in required_fields if field not in variables)
    if missing:
        raise ServiceError(422, f"Missing template variables: {', '.join(missing)}.")
    try:
        rendered = body.format(**variables)
    except Exception as exc:
        raise ServiceError(422, "Template could not be rendered.") from exc
    if not rendered.strip():
        raise ServiceError(422, "Rendered message body cannot be empty.")
    return rendered


def list_messages(
    db: Session,
    company_id: str | None,
    *,
    status: str | None = None,
) -> list[NotificationQueue]:
    scoped_company_id = require_company_id(company_id)
    query = select(NotificationQueue).where(
        NotificationQueue.company_id == scoped_company_id,
        NotificationQueue.channel == CHANNEL,
    )
    if status:
        query = query.where(NotificationQueue.status == status)
    return list(db.scalars(query.order_by(NotificationQueue.created_at.desc())).all())


def get_message(db: Session, company_id: str | None, message_id: str) -> NotificationQueue:
    scoped_company_id = require_company_id(company_id)
    message = db.scalar(
        select(NotificationQueue).where(
            NotificationQueue.company_id == scoped_company_id,
            NotificationQueue.channel == CHANNEL,
            NotificationQueue.id == message_id,
        )
    )
    if message is None:
        raise ServiceError(404, "WhatsApp message not found.")
    return message


def enqueue_message(
    db: Session,
    *,
    company_id: str | None,
    user_id: str,
    payload: WhatsAppMessageEnqueue,
) -> NotificationQueue:
    scoped_company_id = require_company_id(company_id)
    recipient_phone = normalize_phone(payload.recipient_phone)
    if payload.template_id:
        template = get_template(db, scoped_company_id, payload.template_id)
        message_body = render_template(template.body, payload.variables)
        template_id = template.id
    elif payload.body:
        message_body = render_template(payload.body, payload.variables)
        template_id = None
    else:
        raise ServiceError(422, "Either template_id or body is required.")

    if payload.idempotency_key:
        existing = db.scalar(
            select(NotificationQueue).where(
                NotificationQueue.company_id == scoped_company_id,
                NotificationQueue.idempotency_key == payload.idempotency_key,
            )
        )
        if existing is not None:
            return existing

    message = NotificationQueue(
        company_id=scoped_company_id,
        channel=CHANNEL,
        template_id=template_id,
        recipient_phone=recipient_phone,
        message_body=message_body,
        status="queued",
        idempotency_key=payload.idempotency_key,
        metadata_json=payload.metadata,
        created_by_id=user_id,
        scheduled_at=payload.scheduled_at,
    )
    db.add(message)
    db.flush()
    db.refresh(message)
    record_audit(
        db,
        action="whatsapp.message_queued",
        company_id=scoped_company_id,
        user_id=user_id,
        entity_type="notification_queue",
        entity_id=message.id,
        metadata={"template_id": template_id},
    )
    return message


def delivery_logs(
    db: Session,
    company_id: str | None,
    message_id: str,
) -> list[NotificationDeliveryLog]:
    scoped_company_id = require_company_id(company_id)
    return list(
        db.scalars(
            select(NotificationDeliveryLog)
            .where(
                NotificationDeliveryLog.company_id == scoped_company_id,
                NotificationDeliveryLog.notification_id == message_id,
            )
            .order_by(NotificationDeliveryLog.created_at)
        ).all()
    )


def deliver_with_mock_adapter(
    db: Session,
    *,
    company_id: str | None,
    user_id: str,
    message_id: str,
    force_failure: bool = False,
) -> NotificationDeliveryLog:
    scoped_company_id = require_company_id(company_id)
    message = get_message(db, scoped_company_id, message_id)
    adapter = MockWhatsAppAdapter(force_failure=force_failure)
    result = adapter.send(message)
    now = utcnow()
    if result.ok:
        message.status = "sent"
        message.sent_at = now
        message.failed_at = None
        message.last_error = None
        action = "whatsapp.message_sent"
    else:
        message.status = "failed"
        message.failed_at = now
        message.last_error = result.error
        action = "whatsapp.message_failed"

    log = NotificationDeliveryLog(
        company_id=scoped_company_id,
        notification_id=message.id,
        channel=CHANNEL,
        status=result.status,
        adapter=adapter.name,
        provider_message_id=result.provider_message_id,
        error=result.error,
        payload=result.payload or {},
    )
    db.add(log)
    db.flush()
    db.refresh(log)
    record_audit(
        db,
        action=action,
        company_id=scoped_company_id,
        user_id=user_id,
        entity_type="notification_queue",
        entity_id=message.id,
        metadata={"adapter": adapter.name},
    )
    return log
