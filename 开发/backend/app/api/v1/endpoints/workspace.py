from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import get_current_user, require_admin, require_csrf_for_session
from app.core.config import settings
from app.core.db import get_db
from app.core.errors import AppError
from app.core.request_id import get_request_id
from app.models import Conversation, Run, User, Workspace
from app.schemas import ServiceModePatchIn, WorkspacePatchIn

router = APIRouter()


def _env(data: dict) -> dict:
    return {"data": data, "request_id": get_request_id()}


@router.get("/workspace")
async def get_workspace(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    workspace = await db.get(Workspace, user.workspace_id)
    if workspace is None:
        raise AppError(status_code=404, code="workspace_not_found", message="workspace not found")
    return _env(
        {
            "id": workspace.id,
            "name": workspace.name,
            "timezone": workspace.timezone,
            "revision": workspace.revision,
        }
    )


@router.patch("/workspace")
async def patch_workspace(
    payload: WorkspacePatchIn,
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
    _csrf=Depends(require_csrf_for_session),
):
    workspace = (
        await db.execute(
            select(Workspace).where(Workspace.id == user.workspace_id).with_for_update()
        )
    ).scalar_one_or_none()
    if workspace is None:
        raise AppError(status_code=404, code="workspace_not_found", message="workspace not found")
    if payload.expected_revision != workspace.revision:
        raise AppError(
            status_code=409,
            code="config_revision_conflict",
            message="workspace revision changed",
        )

    workspace.name = payload.name.strip()
    workspace.revision += 1
    await db.flush()
    return _env(
        {
            "id": workspace.id,
            "name": workspace.name,
            "timezone": workspace.timezone,
            "revision": workspace.revision,
        }
    )


@router.get("/service-mode")
async def get_service_mode(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    workspace = await db.get(Workspace, user.workspace_id)
    if workspace is None:
        raise AppError(status_code=404, code="workspace_not_found", message="workspace not found")
    return _env(
        {
            "mode": workspace.service_mode,
            "authorization_epoch": workspace.service_epoch,
            "reason": workspace.service_reason,
            "scope": "member_owner",
        }
    )


@router.put("/service-mode")
async def set_service_mode(
    payload: ServiceModePatchIn,
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
    _csrf=Depends(require_csrf_for_session),
):
    workspace = (
        await db.execute(
            select(Workspace).where(Workspace.id == user.workspace_id).with_for_update()
        )
    ).scalar_one_or_none()
    if workspace is None:
        raise AppError(status_code=404, code="workspace_not_found", message="workspace not found")
    if payload.expected_epoch != workspace.service_epoch:
        raise AppError(
            status_code=409,
            code="service_epoch_conflict",
            message="service epoch mismatch",
        )
    if payload.mode == "service_closed" and not (payload.reason or "").strip():
        raise AppError(
            status_code=422,
            code="validation_error",
            message="reason is required when closing service",
        )
    workspace.service_mode = payload.mode
    workspace.service_reason = payload.reason
    workspace.service_epoch += 1
    if payload.mode == "service_closed":
        conversation_ids = select(Conversation.id).where(
            Conversation.workspace_id == user.workspace_id,
            Conversation.deleted_at.is_(None),
        )
        await db.execute(
            update(Run)
            .where(
                Run.conversation_id.in_(conversation_ids),
                Run.status.in_(("created", "running", "reviewing")),
            )
            .values(status="cancelled", error_code="service_paused")
        )
        await db.execute(
            update(Conversation)
            .where(
                Conversation.workspace_id == user.workspace_id,
                Conversation.deleted_at.is_(None),
            )
            .values(
                run_epoch=Conversation.run_epoch + 1,
                revision=Conversation.revision + 1,
            )
        )
    await db.flush()
    return _env(
        {
            "mode": workspace.service_mode,
            "authorization_epoch": workspace.service_epoch,
            "reason": workspace.service_reason,
            "scope": "member_owner",
            "instance_confirmations": [
                {
                    "instance_id": settings.instance_id,
                    "authorization_epoch": workspace.service_epoch,
                    "confirmed": True,
                }
            ],
        }
    )
