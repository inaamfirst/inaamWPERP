from __future__ import annotations

import base64
import hashlib
import hmac
import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from erp.packages.core.catalog_services import require_company_id
from erp.packages.core.config import Settings, get_settings
from erp.packages.core.db.models import Company, License
from erp.packages.core.services import ServiceError, record_audit, to_utc, utcnow


@dataclass(frozen=True)
class LicenseState:
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


@dataclass(frozen=True)
class LicenseValidation:
    configured: bool
    status: str
    detail: str
    validated_at: datetime


@dataclass(frozen=True)
class LicenseServerResult:
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


def hash_license_key(license_key: str) -> str:
    settings = get_settings()
    return hmac.new(
        settings.secret_key.encode(),
        license_key.encode(),
        hashlib.sha256,
    ).hexdigest()


def sign_payload(payload: dict[str, Any], signing_key: str) -> tuple[str, str]:
    serialized = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    encoded = base64.urlsafe_b64encode(serialized.encode()).decode()
    signature = hmac.new(signing_key.encode(), encoded.encode(), hashlib.sha256).hexdigest()
    return encoded, signature


def verify_signed_payload(encoded: str, signature: str, signing_key: str) -> dict[str, Any]:
    expected = hmac.new(signing_key.encode(), encoded.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, signature):
        raise ServiceError(403, "Offline license signature is invalid.")
    raw = base64.urlsafe_b64decode(encoded.encode()).decode()
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ServiceError(403, "Offline license payload is invalid.")
    return value


def parse_datetime(value: object) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return to_utc(value)
    return to_utc(datetime.fromisoformat(str(value)))


def offline_license_path(company_id: str, settings: Settings | None = None) -> Path:
    active_settings = settings or get_settings()
    configured = Path(active_settings.license_offline_file)
    if configured.suffix:
        parent = configured.parent
        return parent / f"{company_id}-{configured.name}"
    return configured / f"{company_id}.license.json"


def write_offline_license_file(company_id: str, result: LicenseServerResult) -> Path:
    settings = get_settings()
    path = offline_license_path(company_id, settings)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "signed_payload": result.signed_payload,
                "signature": result.signature,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return path


def read_offline_license_file(company_id: str) -> dict[str, Any] | None:
    settings = get_settings()
    path = offline_license_path(company_id, settings)
    if not path.exists():
        return None
    envelope = json.loads(path.read_text(encoding="utf-8"))
    return verify_signed_payload(
        str(envelope["signed_payload"]),
        str(envelope["signature"]),
        settings.license_offline_signing_key,
    )


def license_for_company(db: Session, company_id: str) -> License | None:
    return db.scalar(
        select(License)
        .where(License.company_id == company_id)
        .order_by(License.created_at.desc())
    )


def local_license_server_result(
    *,
    license_key: str,
    company_id: str,
    company_name: str,
    device_id: str,
    plan: str,
) -> LicenseServerResult:
    settings = get_settings()
    now = utcnow()
    expires_at = now + timedelta(days=365)
    grace_expires_at = expires_at + timedelta(days=14)
    license_key_hash = hash_license_key(license_key)
    payload = {
        "license_id": license_key_hash[:24],
        "license_key_hash": license_key_hash,
        "company_id": company_id,
        "company_name": company_name,
        "device_id": device_id,
        "status": "active",
        "plan": plan,
        "activated_at": now.isoformat(),
        "expires_at": expires_at.isoformat(),
        "grace_expires_at": grace_expires_at.isoformat(),
    }
    signed_payload, signature = sign_payload(payload, settings.license_offline_signing_key)
    return LicenseServerResult(
        license_id=str(payload["license_id"]),
        license_key_hash=license_key_hash,
        status="active",
        plan=plan,
        device_id=device_id,
        activated_at=now,
        expires_at=expires_at,
        grace_expires_at=grace_expires_at,
        signed_payload=signed_payload,
        signature=signature,
    )


def request_license_activation(
    *,
    license_key: str,
    company_id: str,
    company_name: str,
    plan: str,
) -> LicenseServerResult:
    settings = get_settings()
    device_id = settings.license_device_id
    if not settings.license_server_url.strip():
        return local_license_server_result(
            license_key=license_key,
            company_id=company_id,
            company_name=company_name,
            device_id=device_id,
            plan=plan,
        )
    response = httpx.post(
        f"{settings.license_server_url.rstrip('/')}/license/v1/licenses/activate",
        json={
            "license_key": license_key,
            "company_id": company_id,
            "company_name": company_name,
            "device_id": device_id,
            "plan": plan,
        },
        timeout=10.0,
    )
    if response.status_code >= 400:
        raise ServiceError(response.status_code, "License server rejected activation.")
    payload = response.json()
    return LicenseServerResult(
        license_id=str(payload["license_id"]),
        license_key_hash=str(payload["license_key_hash"]),
        status=str(payload["status"]),
        plan=str(payload["plan"]),
        device_id=str(payload["device_id"]),
        activated_at=parse_datetime(payload.get("activated_at")),
        expires_at=parse_datetime(payload.get("expires_at")),
        grace_expires_at=parse_datetime(payload.get("grace_expires_at")),
        signed_payload=str(payload["signed_payload"]),
        signature=str(payload["signature"]),
    )


def activate_license(
    db: Session,
    *,
    company_id: str | None,
    user_id: str,
    license_key: str,
    plan: str,
) -> License:
    scoped_company_id = require_company_id(company_id)
    normalized_plan = plan.strip().lower()
    if not normalized_plan:
        raise ServiceError(422, "License plan is required.")
    company = db.get(Company, scoped_company_id)
    if company is None:
        raise ServiceError(404, "Company not found.")

    result = request_license_activation(
        license_key=license_key,
        company_id=scoped_company_id,
        company_name=company.name,
        plan=normalized_plan,
    )
    if result.status not in {"active", "grace"}:
        raise ServiceError(403, f"License is not active: {result.status}.")

    license_row = license_for_company(db, scoped_company_id)
    if license_row is None:
        license_row = License(company_id=scoped_company_id)
        db.add(license_row)
    license_row.license_key_hash = result.license_key_hash
    license_row.status = result.status
    license_row.plan = result.plan
    license_row.activated_at = result.activated_at
    license_row.expires_at = result.expires_at
    offline_path = write_offline_license_file(scoped_company_id, result)
    license_row.metadata_json = {
        "activation_mode": "online_server" if get_settings().license_server_url else "local_server",
        "license_id": result.license_id,
        "device_id": result.device_id,
        "grace_expires_at": result.grace_expires_at.isoformat()
        if result.grace_expires_at
        else None,
        "last_validated_at": utcnow().isoformat(),
        "offline_license_path": str(offline_path),
    }
    db.flush()
    db.refresh(license_row)
    record_audit(
        db,
        action="licensing.activated",
        company_id=scoped_company_id,
        user_id=user_id,
        entity_type="license",
        entity_id=license_row.id,
        metadata={
            "plan": result.plan,
            "activation_mode": license_row.metadata_json["activation_mode"],
            "license_id": result.license_id,
        },
    )
    return license_row


def revoke_license(
    db: Session,
    *,
    company_id: str | None,
    user_id: str,
    reason: str | None = None,
) -> License:
    scoped_company_id = require_company_id(company_id)
    license_row = license_for_company(db, scoped_company_id)
    if license_row is None:
        raise ServiceError(404, "License not found.")
    license_row.status = "revoked"
    metadata = dict(license_row.metadata_json or {})
    metadata["revoked_at"] = utcnow().isoformat()
    metadata["revocation_reason"] = reason
    license_row.metadata_json = metadata
    db.flush()
    record_audit(
        db,
        action="licensing.revoked",
        company_id=scoped_company_id,
        user_id=user_id,
        entity_type="license",
        entity_id=license_row.id,
        metadata={"reason": reason},
    )
    return license_row


def status_from_dates(
    status: str,
    expires_at: datetime | None,
    grace_expires_at: datetime | None,
) -> str:
    if status == "revoked":
        return "revoked"
    now = utcnow()
    normalized_expires_at = to_utc(expires_at)
    normalized_grace_expires_at = to_utc(grace_expires_at)
    if normalized_expires_at and now > normalized_expires_at:
        return (
            "grace"
            if normalized_grace_expires_at and now <= normalized_grace_expires_at
            else "expired"
        )
    return status


def license_state(db: Session, company_id: str | None) -> LicenseState:
    scoped_company_id = require_company_id(company_id)
    license_row = license_for_company(db, scoped_company_id)
    if license_row is None:
        return LicenseState(
            configured=False,
            status="inactive",
            plan=None,
            activated_at=None,
            expires_at=None,
            grace_expires_at=None,
        )

    metadata = dict(license_row.metadata_json or {})
    grace_expires_at = parse_datetime(metadata.get("grace_expires_at"))
    status = status_from_dates(license_row.status, license_row.expires_at, grace_expires_at)
    if status in {"expired", "inactive"}:
        offline_payload = read_offline_license_file(scoped_company_id)
        if offline_payload:
            offline_status = status_from_dates(
                str(offline_payload.get("status") or status),
                parse_datetime(offline_payload.get("expires_at")),
                parse_datetime(offline_payload.get("grace_expires_at")),
            )
            if offline_status == "grace":
                status = "grace"

    return LicenseState(
        configured=True,
        status=status,
        plan=license_row.plan,
        activated_at=license_row.activated_at,
        expires_at=license_row.expires_at,
        grace_expires_at=grace_expires_at,
        license_id=metadata.get("license_id"),
        device_id=metadata.get("device_id"),
        activation_mode=metadata.get("activation_mode"),
        last_validated_at=parse_datetime(metadata.get("last_validated_at")),
    )


def validate_license(db: Session, company_id: str | None) -> LicenseValidation:
    state = license_state(db, company_id)
    now = utcnow()
    if not state.configured:
        return LicenseValidation(False, "inactive", "License is not configured.", now)
    if state.status in {"active", "grace"}:
        return LicenseValidation(True, state.status, "License is valid.", now)
    return LicenseValidation(True, state.status, f"License is {state.status}.", now)
