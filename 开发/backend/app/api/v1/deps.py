from __future__ import annotations

from datetime import timedelta

from fastapi import Depends, Header, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.db import get_db
from app.core.errors import AppError
from app.core.security import constant_compare, ensure_utc, hash_session_token, utc_now
from app.models import User, UserSession


async def get_current_session(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> UserSession:
    token = request.cookies.get(settings.session_cookie_name)
    if not token:
        raise AppError(
            status_code=status.HTTP_401_UNAUTHORIZED,
            code="unauthenticated",
            message="no active session",
        )
    token_hash = hash_session_token(token)
    now = utc_now()
    stmt = select(UserSession).where(UserSession.token_hash == token_hash)
    row = (await db.execute(stmt)).scalar_one_or_none()
    if row is None or row.revoked_at is not None:
        raise AppError(
            status_code=status.HTTP_401_UNAUTHORIZED,
            code="unauthenticated",
            message="session not found or revoked",
        )
    if ensure_utc(row.expires_at) <= now or ensure_utc(row.absolute_expires_at) <= now:
        row.revoked_at = now
        await db.commit()
        raise AppError(
            status_code=status.HTTP_401_UNAUTHORIZED,
            code="session_expired",
            message="session has expired",
        )
    row.last_seen_at = now
    idle_extension = now + timedelta(minutes=settings.session_idle_ttl_minutes)
    row.expires_at = min(idle_extension, ensure_utc(row.absolute_expires_at))
    await db.flush()
    return row


async def get_current_user(
    session: UserSession = Depends(get_current_session),
    db: AsyncSession = Depends(get_db),
) -> User:
    row = await db.get(User, session.user_id)
    if row is None or not row.is_active:
        raise AppError(
            status_code=status.HTTP_401_UNAUTHORIZED,
            code="user_inactive",
            message="user no longer active",
        )
    return row


def require_csrf_token(
    x_csrf_token: str | None = Header(default=None, convert_underscores=False, alias="x-csrf-token"),
) -> str:
    if not x_csrf_token:
        raise AppError(
            status_code=status.HTTP_401_UNAUTHORIZED,
            code="csrf_missing",
            message="csrf token is required",
        )
    return x_csrf_token


def require_trusted_origin(request: Request) -> None:
    origin = request.headers.get("origin")
    allowed = {item.rstrip("/") for item in settings.allowed_origins}
    allowed.add(settings.api_origin.rstrip("/"))
    if origin is None or origin.rstrip("/") not in allowed:
        raise AppError(
            status_code=status.HTTP_403_FORBIDDEN,
            code="origin_invalid",
            message="request origin is not trusted",
        )


def require_csrf_for_session(
    session: UserSession = Depends(get_current_session),
    x_csrf_token: str | None = Depends(require_csrf_token),
    _origin: None = Depends(require_trusted_origin),
) -> None:
    if not session.csrf_token or not x_csrf_token:
        raise AppError(
            status_code=status.HTTP_401_UNAUTHORIZED,
            code="csrf_invalid",
            message="csrf token required",
        )
    if not constant_compare(session.csrf_token, x_csrf_token):
        raise AppError(
            status_code=status.HTTP_403_FORBIDDEN,
            code="csrf_invalid",
            message="csrf token mismatch",
        )
def require_pre_auth_csrf(
    request: Request,
    x_csrf_token: str | None = Header(default=None, convert_underscores=False, alias="x-csrf-token"),
    _origin: None = Depends(require_trusted_origin),
) -> None:
    issued_csrf = request.cookies.get(settings.preauth_csrf_cookie_name)
    if not issued_csrf or not x_csrf_token:
        raise AppError(
            status_code=status.HTTP_401_UNAUTHORIZED,
            code="csrf_missing",
            message="pre-auth csrf token is required",
        )
    if not constant_compare(issued_csrf, x_csrf_token):
        raise AppError(
            status_code=status.HTTP_403_FORBIDDEN,
            code="csrf_invalid",
            message="pre-auth csrf token mismatch",
        )


def require_admin(user: User = Depends(get_current_user)) -> User:
    if user.role != "admin":
        raise AppError(
            status_code=status.HTTP_403_FORBIDDEN,
            code="permission_denied",
            message="admin role required",
        )
    return user
