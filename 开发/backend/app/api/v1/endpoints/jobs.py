from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import get_current_user
from app.core.config import settings
from app.core.db import get_db
from app.core.errors import AppError
from app.core.request_id import get_request_id
from app.core.security import decode_cursor, encode_cursor, ensure_utc
from app.models import DeletionReceipt, Job, User

router = APIRouter(prefix="/jobs")


def _env(payload: object) -> dict[str, object]:
    return {"data": payload, "request_id": get_request_id()}


async def _job_payload(db: AsyncSession, job: Job) -> dict[str, object]:
    receipt = (
        await db.execute(select(DeletionReceipt).where(DeletionReceipt.job_id == job.id))
    ).scalar_one_or_none()
    return {
        "id": job.id,
        "type": job.type,
        "status": job.status,
        "stage": job.stage,
        "created_at": ensure_utc(job.created_at).isoformat(),
        "updated_at": ensure_utc(job.updated_at).isoformat(),
        "error_code": job.error_code,
        "retryable": job.retryable,
        "receipt_id": receipt.id if receipt else None,
        "artifact_id": None,
    }


def _job_scope(user: User):
    conditions = [Job.workspace_id == user.workspace_id]
    if user.role != "admin":
        conditions.append(Job.actor_id == user.id)
    return conditions


@router.get("")
async def list_jobs(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    limit: int = Query(default=20, ge=1, le=100),
    cursor: str | None = None,
    job_type: str | None = Query(default=None, alias="type", max_length=32),
    status_filter: str | None = Query(default=None, alias="status", max_length=32),
):
    statement = select(Job).where(*_job_scope(user))
    if job_type:
        statement = statement.where(Job.type == job_type)
    if status_filter:
        statement = statement.where(Job.status == status_filter)
    if cursor:
        try:
            decoded = decode_cursor(cursor, settings.secret_key)
            if (
                decoded.get("actor_id") != user.id
                or decoded.get("type") != job_type
                or decoded.get("status") != status_filter
            ):
                raise ValueError("cursor scope does not match request")
            created_at_raw = decoded["created_at"]
            job_id = decoded["id"]
            if not isinstance(created_at_raw, str) or not isinstance(job_id, str):
                raise ValueError("invalid cursor payload")
            created_at = ensure_utc(datetime.fromisoformat(created_at_raw))
        except (KeyError, TypeError, ValueError) as exc:
            raise AppError(status_code=422, code="cursor_invalid", message="invalid jobs cursor") from exc
        statement = statement.where(
            or_(
                Job.created_at < created_at,
                and_(Job.created_at == created_at, Job.id < job_id),
            )
        )
    rows = list(
        (
            await db.execute(statement.order_by(Job.created_at.desc(), Job.id.desc()).limit(limit + 1))
        ).scalars().all()
    )
    has_more = len(rows) > limit
    visible = rows[:limit]
    return _env(
        {
            "items": [await _job_payload(db, job) for job in visible],
            "next_cursor": (
                encode_cursor(
                    {
                        "actor_id": user.id,
                        "type": job_type,
                        "status": status_filter,
                        "created_at": ensure_utc(visible[-1].created_at).isoformat(),
                        "id": visible[-1].id,
                    },
                    settings.secret_key,
                )
                if has_more and visible
                else None
            ),
            "has_more": has_more,
        }
    )


@router.get("/{job_id}")
async def get_job(
    job_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    job = (
        await db.execute(select(Job).where(Job.id == job_id, *_job_scope(user)))
    ).scalar_one_or_none()
    if job is None:
        raise AppError(status_code=404, code="resource_not_found", message="job not found")
    return _env(await _job_payload(db, job))
