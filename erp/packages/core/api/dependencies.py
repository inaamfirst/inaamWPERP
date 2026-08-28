from __future__ import annotations

from collections.abc import Callable
from typing import Annotated

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from erp.packages.core.db.session import get_session
from erp.packages.core.services import AuthContext, ServiceError, context_from_token

bearer_scheme = HTTPBearer(auto_error=False)
BearerCredentials = Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)]
DbSession = Annotated[Session, Depends(get_session)]


def service_error_to_http(error: ServiceError) -> HTTPException:
    return HTTPException(status_code=error.status_code, detail=error.message)


def current_context(
    credentials: BearerCredentials,
    db: DbSession,
) -> AuthContext:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(status_code=401, detail="Bearer token required.")
    try:
        return context_from_token(db, credentials.credentials)
    except ServiceError as exc:
        raise service_error_to_http(exc) from exc


CurrentContext = Annotated[AuthContext, Depends(current_context)]


def optional_current_context(
    credentials: BearerCredentials,
    db: DbSession,
) -> AuthContext | None:
    """Return a valid context when present without making logout token-oracular."""

    if credentials is None or credentials.scheme.lower() != "bearer":
        return None
    try:
        return context_from_token(db, credentials.credentials)
    except ServiceError:
        return None


OptionalCurrentContext = Annotated[AuthContext | None, Depends(optional_current_context)]


def require_permission(permission: str) -> Callable[[AuthContext], AuthContext]:
    def dependency(context: CurrentContext) -> AuthContext:
        if context.user.must_change_password:
            raise HTTPException(
                status_code=403,
                detail="Password change is required before using protected features.",
            )
        if permission not in context.permissions:
            raise HTTPException(
                status_code=403,
                detail=f"Missing required permission: {permission}",
            )
        return context

    return dependency


def require_any_permission(*permissions: str) -> Callable[[AuthContext], AuthContext]:
    if not permissions:
        raise ValueError("At least one permission is required.")

    def dependency(context: CurrentContext) -> AuthContext:
        if context.user.must_change_password:
            raise HTTPException(
                status_code=403,
                detail="Password change is required before using protected features.",
            )
        if not any(permission in context.permissions for permission in permissions):
            expected = " or ".join(permissions)
            raise HTTPException(status_code=403, detail=f"Missing one of: {expected}")
        return context

    return dependency
