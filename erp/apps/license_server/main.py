from __future__ import annotations

import hmac
from collections.abc import Callable, Iterator
from datetime import timedelta
from typing import Annotated

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from sqlalchemy import inspect, select, text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from erp import __version__
from erp.packages.core.config import Settings, get_settings
from erp.packages.core.db.models import LicenseServerEvent, LicenseServerRecord
from erp.packages.core.db.session import SessionLocal
from erp.packages.core.licensing_services import (
    LicenseServerResult,
    hash_license_key,
    local_license_server_result,
    sign_payload,
)
from erp.packages.core.schemas import (
    LicenseServerActivationRequest,
    LicenseServerMutationRequest,
    LicenseServerResponse,
    LicenseServerValidationRequest,
)
from erp.packages.core.services import utcnow

SessionFactory = Callable[[], Session]
LICENSE_TABLES = {"license_server_records", "license_server_events"}


def get_license_db(request: Request) -> Iterator[Session]:
    session_factory: SessionFactory = request.app.state.license_session_factory
    db = session_factory()
    try:
        yield db
    finally:
        db.close()


DbSession = Annotated[Session, Depends(get_license_db)]


def _as_result(record: LicenseServerRecord) -> LicenseServerResult:
    return LicenseServerResult(
        license_id=record.id,
        license_key_hash=record.license_key_hash,
        status=record.status,
        plan=record.plan,
        device_id=record.device_id,
        activated_at=record.activated_at,
        expires_at=record.expires_at,
        grace_expires_at=record.grace_expires_at,
        signed_payload=record.signed_payload,
        signature=record.signature,
    )


def _apply_result(record: LicenseServerRecord, result: LicenseServerResult) -> None:
    record.status = result.status
    record.plan = result.plan
    record.device_id = result.device_id
    record.activated_at = result.activated_at
    record.expires_at = result.expires_at
    record.grace_expires_at = result.grace_expires_at
    record.signed_payload = result.signed_payload
    record.signature = result.signature


def create_app(
    *,
    settings: Settings | None = None,
    session_factory: SessionFactory | None = None,
) -> FastAPI:
    active_settings = settings or get_settings()
    active_session_factory = session_factory or SessionLocal
    docs_url = "/docs" if active_settings.effective_docs_enabled else None
    app = FastAPI(
        title=f"{active_settings.app_name} License Server",
        version=__version__,
        docs_url=docs_url,
        redoc_url="/redoc" if docs_url else None,
    )
    app.state.license_session_factory = active_session_factory

    def require_admin(admin_key: str | None) -> None:
        configured = active_settings.license_server_admin_key
        if admin_key is None or not hmac.compare_digest(admin_key, configured):
            raise HTTPException(status_code=401, detail="License server admin key required.")

    def to_response(record: LicenseServerRecord) -> LicenseServerResponse:
        result = _as_result(record)
        return LicenseServerResponse(
            license_id=result.license_id,
            license_key_hash=result.license_key_hash,
            status=result.status,
            plan=result.plan,
            device_id=result.device_id,
            activated_at=result.activated_at,
            expires_at=result.expires_at,
            grace_expires_at=result.grace_expires_at,
            signed_payload=result.signed_payload,
            signature=result.signature,
        )

    def resign(result: LicenseServerResult, status: str) -> LicenseServerResult:
        payload = {
            "license_id": result.license_id,
            "license_key_hash": result.license_key_hash,
            "device_id": result.device_id,
            "status": status,
            "plan": result.plan,
            "activated_at": (
                result.activated_at.isoformat() if result.activated_at else None
            ),
            "expires_at": result.expires_at.isoformat() if result.expires_at else None,
            "grace_expires_at": (
                result.grace_expires_at.isoformat() if result.grace_expires_at else None
            ),
        }
        signed_payload, signature = sign_payload(
            payload, active_settings.license_offline_signing_key
        )
        return LicenseServerResult(
            license_id=result.license_id,
            license_key_hash=result.license_key_hash,
            status=status,
            plan=result.plan,
            device_id=result.device_id,
            activated_at=result.activated_at,
            expires_at=result.expires_at,
            grace_expires_at=result.grace_expires_at,
            signed_payload=signed_payload,
            signature=signature,
        )

    def find_record(
        db: Session,
        *,
        license_id: str | None = None,
        license_key_hash: str | None = None,
        for_update: bool = False,
    ) -> LicenseServerRecord | None:
        statement = select(LicenseServerRecord)
        if license_key_hash:
            statement = statement.where(
                LicenseServerRecord.license_key_hash == license_key_hash
            )
        elif license_id:
            statement = statement.where(LicenseServerRecord.id == license_id)
        else:
            return None
        if for_update:
            statement = statement.with_for_update()
        return db.scalar(statement)

    def add_event(
        db: Session,
        record: LicenseServerRecord,
        event_type: str,
        *,
        reason: str | None = None,
        metadata: dict[str, object] | None = None,
    ) -> None:
        db.add(
            LicenseServerEvent(
                license_id=record.id,
                event_type=event_type,
                reason=reason,
                metadata_json=metadata or {},
            )
        )

    @app.get("/license/v1/health", tags=["license-server"])
    def health(db: DbSession) -> dict[str, str]:
        try:
            db.execute(text("SELECT 1"))
            tables = set(inspect(db.get_bind()).get_table_names())
        except SQLAlchemyError as exc:
            raise HTTPException(status_code=503, detail="License database unavailable.") from exc
        if LICENSE_TABLES - tables:
            raise HTTPException(
                status_code=503,
                detail="License database migrations are incomplete.",
            )
        return {"status": "healthy", "version": __version__}

    @app.post(
        "/license/v1/licenses/activate",
        response_model=LicenseServerResponse,
        tags=["license-server"],
    )
    def activate(
        payload: LicenseServerActivationRequest,
        db: DbSession,
    ) -> LicenseServerResponse:
        license_key_hash = hash_license_key(payload.license_key)
        existing = find_record(db, license_key_hash=license_key_hash, for_update=True)
        if existing is not None:
            if existing.status == "revoked":
                return to_response(existing)
            if existing.device_id != payload.device_id:
                raise HTTPException(status_code=409, detail="License is bound to another device.")
            return to_response(existing)

        result = local_license_server_result(
            license_key=payload.license_key,
            company_id=payload.company_id,
            company_name=payload.company_name,
            device_id=payload.device_id,
            plan=payload.plan,
        )
        record = LicenseServerRecord(
            id=result.license_id,
            license_key_hash=result.license_key_hash,
            company_id=payload.company_id,
            company_name=payload.company_name,
            device_id=result.device_id,
            status=result.status,
            plan=result.plan,
            activated_at=result.activated_at,
            expires_at=result.expires_at,
            grace_expires_at=result.grace_expires_at,
            signed_payload=result.signed_payload,
            signature=result.signature,
        )
        db.add(record)
        add_event(db, record, "activated", metadata={"plan": result.plan})
        try:
            db.commit()
        except IntegrityError as exc:
            db.rollback()
            existing = find_record(db, license_key_hash=license_key_hash)
            if existing is None:
                raise
            if existing.device_id != payload.device_id:
                raise HTTPException(
                    status_code=409, detail="License is bound to another device."
                ) from exc
            return to_response(existing)
        db.refresh(record)
        return to_response(record)

    @app.post(
        "/license/v1/licenses/validate",
        response_model=LicenseServerResponse,
        tags=["license-server"],
    )
    def validate(
        payload: LicenseServerValidationRequest,
        db: DbSession,
    ) -> LicenseServerResponse:
        record = find_record(
            db,
            license_id=payload.license_id,
            license_key_hash=payload.license_key_hash,
        )
        if record is None:
            raise HTTPException(status_code=404, detail="License not found.")
        if record.device_id != payload.device_id:
            raise HTTPException(status_code=403, detail="License is not valid for this device.")
        return to_response(record)

    @app.post(
        "/license/v1/licenses/revoke",
        response_model=LicenseServerResponse,
        tags=["license-server"],
    )
    def revoke(
        payload: LicenseServerMutationRequest,
        db: DbSession,
        x_license_admin_key: str | None = Header(default=None),
    ) -> LicenseServerResponse:
        require_admin(x_license_admin_key)
        key_hash = hash_license_key(payload.license_key) if payload.license_key else None
        record = find_record(
            db,
            license_id=payload.license_id,
            license_key_hash=key_hash,
            for_update=True,
        )
        if record is None:
            raise HTTPException(status_code=404, detail="License not found.")
        revoked = resign(_as_result(record), "revoked")
        _apply_result(record, revoked)
        add_event(db, record, "revoked", reason=payload.reason)
        db.commit()
        db.refresh(record)
        return to_response(record)

    @app.post(
        "/license/v1/licenses/renew",
        response_model=LicenseServerResponse,
        tags=["license-server"],
    )
    def renew(
        payload: LicenseServerMutationRequest,
        db: DbSession,
        x_license_admin_key: str | None = Header(default=None),
    ) -> LicenseServerResponse:
        require_admin(x_license_admin_key)
        key_hash = hash_license_key(payload.license_key) if payload.license_key else None
        record = find_record(
            db,
            license_id=payload.license_id,
            license_key_hash=key_hash,
            for_update=True,
        )
        if record is None:
            raise HTTPException(status_code=404, detail="License not found.")
        now = utcnow()
        expires_at = now + timedelta(days=payload.extend_days)
        renewed = LicenseServerResult(
            license_id=record.id,
            license_key_hash=record.license_key_hash,
            status="active",
            plan=record.plan,
            device_id=record.device_id,
            activated_at=record.activated_at or now,
            expires_at=expires_at,
            grace_expires_at=expires_at + timedelta(days=14),
            signed_payload=record.signed_payload,
            signature=record.signature,
        )
        renewed = resign(renewed, "active")
        _apply_result(record, renewed)
        add_event(
            db,
            record,
            "renewed",
            reason=payload.reason,
            metadata={"extend_days": payload.extend_days},
        )
        db.commit()
        db.refresh(record)
        return to_response(record)

    return app


app = create_app()
