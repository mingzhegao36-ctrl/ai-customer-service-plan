from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, Depends, Header, Request, Response, status
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import (
    get_current_user,
    require_pre_auth_csrf,
    require_trusted_origin,
)
from app.core.config import settings
from app.core.db import get_db
from app.core.errors import AppError
from app.core.request_id import get_request_id
from app.core.security import (
    constant_compare,
    ensure_utc,
    generate_token,
    hash_session_token,
    utc_now,
    verify_password,
)
from app.models import LoginRateLimit, User, UserSession, Workspace
from app.schemas import LoginIn

router = APIRouter()


def _user_payload(user: User, workspace: Workspace | None) -> dict:
    workspace_info = None if workspace is None else {"id": workspace.id, "name": workspace.name, "timezone": workspace.timezone}
    return {
        "id": user.id,
        "username": user.username,
        "role": user.role,
        "workspace": workspace_info,
    }


def _envelope(data: dict) -> dict:
    return {"data": data, "request_id": get_request_id()}


async def _login_rate_limit_row(
    db: AsyncSession,
    *,
    request: Request,
    username: str,
) -> LoginRateLimit:
    client_host = request.client.host if request.client else "unknown"
    fingerprint = hash_session_token(f"{settings.secret_key}:{client_host}:{username}")
    now = utc_now()
    values = {
        "key_hash": fingerprint,
        "window_started_at": now,
        "attempt_count": 0,
        "updated_at": now,
    }
    dialect_name = db.bind.dialect.name if db.bind is not None else ""
    if dialect_name == "postgresql":
        await db.execute(
            postgresql_insert(LoginRateLimit)
            .values(**values)
            .on_conflict_do_nothing(index_elements=["key_hash"])
        )
    elif dialect_name == "sqlite":
        await db.execute(
            sqlite_insert(LoginRateLimit)
            .values(**values)
            .on_conflict_do_nothing(index_elements=["key_hash"])
        )
    else:
        existing = await db.get(LoginRateLimit, fingerprint)
        if existing is None:
            db.add(LoginRateLimit(**values))
            await db.flush()
    row = (
        await db.execute(
            select(LoginRateLimit)
            .where(LoginRateLimit.key_hash == fingerprint)
            .with_for_update()
        )
    ).scalar_one()
    if now - ensure_utc(row.window_started_at) >= timedelta(
        seconds=settings.login_rate_limit_window_seconds
    ):
        row.window_started_at = now
        row.attempt_count = 0
    if row.attempt_count >= settings.login_rate_limit_attempts:
        raise AppError(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            code="rate_limited",
            message="too many login attempts",
            retryable=True,
        )
    return row


@router.get("/csrf")
async def get_csrf_token(
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
):
    raw_token = request.cookies.get(settings.session_cookie_name)
    if raw_token:
        session = (
            await db.execute(
                select(UserSession).where(UserSession.token_hash == hash_session_token(raw_token))
            )
        ).scalar_one_or_none()
        now = utc_now()
        if (
            session is not None
            and session.revoked_at is None
            and ensure_utc(session.expires_at) > now
            and ensure_utc(session.absolute_expires_at) > now
        ):
            response.headers["Cache-Control"] = "no-store"
            return _envelope(
                {"csrf_token": session.csrf_token, "expires_in": settings.csrf_ttl_seconds}
            )
    token = generate_token()
    response.set_cookie(
        key=settings.preauth_csrf_cookie_name,
        value=token,
        max_age=settings.csrf_ttl_seconds,
        httponly=False,
        secure=settings.cookie_secure,
        samesite=settings.cookie_samesite,
        path="/",
        domain=None if settings.cookie_domain == "" else settings.cookie_domain,
    )
    response.headers["Cache-Control"] = "no-store"
    return _envelope({"csrf_token": token, "expires_in": settings.csrf_ttl_seconds})


@router.post("/login")
async def login(
    form: LoginIn,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
    _pre_auth=Depends(require_pre_auth_csrf),
):
    rate_limit = await _login_rate_limit_row(db, request=request, username=form.username)

    stmt = select(User).where(User.username == form.username)
    user = (await db.execute(stmt)).scalar_one_or_none()
    if user is None or not user.is_active or not verify_password(form.password, user.password_hash):
        rate_limit.attempt_count += 1
        rate_limit.updated_at = utc_now()
        await db.commit()
        raise AppError(status_code=status.HTTP_401_UNAUTHORIZED, code="auth_failed", message="invalid credentials")
    await db.delete(rate_limit)

    workspace = await db.get(Workspace, user.workspace_id)
    now = utc_now()
    expires_at = now + timedelta(minutes=settings.session_idle_ttl_minutes)
    absolute_hours = (
        settings.session_remember_absolute_ttl_hours
        if form.remember_me
        else settings.session_absolute_ttl_hours
    )
    absolute_expires_at = now + timedelta(hours=absolute_hours)
    raw_token = generate_token()
    csrf = generate_token()

    session = UserSession(
        user_id=user.id,
        token_hash=hash_session_token(raw_token),
        csrf_token=csrf,
        created_at=now,
        last_seen_at=now,
        expires_at=expires_at,
        absolute_expires_at=absolute_expires_at,
    )
    db.add(session)
    await db.flush()

    cookie_domain = None if settings.cookie_domain == "" else settings.cookie_domain
    response.delete_cookie(
        settings.preauth_csrf_cookie_name,
        path="/",
        domain=cookie_domain,
    )
    response.set_cookie(
        key=settings.session_cookie_name,
        value=raw_token,
        max_age=int((absolute_expires_at - now).total_seconds()),
        httponly=True,
        secure=settings.cookie_secure,
        samesite=settings.cookie_samesite,
        path="/",
        domain=cookie_domain,
    )
    response_payload = {
        "user": _user_payload(user, workspace),
        "permissions": [user.role],
        "session": {
            "expires_in": int((absolute_expires_at - now).total_seconds()),
            "csrf_token": csrf,
            "revoked": False,
        },
    }
    return _envelope(response_payload)


@router.get("/me")
async def me(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    workspace = await db.get(Workspace, user.workspace_id)
    return _envelope(
        {
            "user": _user_payload(user, workspace),
            "permissions": [user.role],
        }
    )


@router.post("/logout")
async def logout(
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
    x_csrf_token: str | None = Header(default=None, alias="x-csrf-token"),
    _origin: None = Depends(require_trusted_origin),
):
    raw_token = request.cookies.get(settings.session_cookie_name)
    if raw_token:
        session = (
            await db.execute(
                select(UserSession).where(
                    UserSession.token_hash == hash_session_token(raw_token)
                )
            )
        ).scalar_one_or_none()
        if session is not None and session.revoked_at is None:
            if not x_csrf_token or not constant_compare(session.csrf_token, x_csrf_token):
                raise AppError(
                    status_code=status.HTTP_403_FORBIDDEN,
                    code="csrf_invalid",
                    message="csrf token mismatch",
                )
            session.revoked_at = utc_now()

    response.delete_cookie(
        settings.session_cookie_name,
        path="/",
        domain=None if settings.cookie_domain == "" else settings.cookie_domain,
    )
    response.status_code = status.HTTP_204_NO_CONTENT
    return response
