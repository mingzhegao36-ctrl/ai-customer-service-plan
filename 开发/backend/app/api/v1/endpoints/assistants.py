from __future__ import annotations

from fastapi import APIRouter, Depends, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import get_current_user, require_admin, require_csrf_for_session
from app.core.db import get_db
from app.core.errors import AppError
from app.core.request_id import get_request_id
from app.models import (
    Assistant,
    AssistantVersion,
    BudgetPolicy,
    ModelDeployment,
    ProviderConnection,
    User,
)
from app.schemas import (
    AssistantCreateIn,
    AssistantPatchIn,
    AssistantVersionCreateIn,
    DefaultVersionIn,
    RevisionActionIn,
    RollbackIn,
)

router = APIRouter(prefix="/assistants")
versions_router = APIRouter(prefix="/assistant-versions")


def _env(payload: object) -> dict[str, object]:
    return {"data": payload, "request_id": get_request_id()}


def _assistant_payload(assistant: Assistant) -> dict[str, object]:
    return {
        "id": assistant.id,
        "name": assistant.name,
        "description": assistant.description,
        "revision": assistant.revision,
        "default_version_id": assistant.default_version_id,
        "created_at": assistant.created_at.isoformat(),
    }


def _version_payload(version: AssistantVersion, *, include_prompt: bool) -> dict[str, object]:
    payload: dict[str, object] = {
        "id": version.id,
        "assistant_id": version.assistant_id,
        "deployment_id": version.deployment_id,
        "policy_version": version.policy_version,
        "revision": version.revision,
        "status": version.status,
        "authorization_epoch": version.authorization_epoch,
        "reason": version.reason,
        "created_at": version.created_at.isoformat(),
    }
    if include_prompt:
        payload["prompt"] = version.prompt
    return payload


async def _assistant_for_workspace(
    db: AsyncSession,
    assistant_id: str,
    workspace_id: str,
    *,
    for_update: bool = False,
) -> Assistant:
    statement = select(Assistant).where(
        Assistant.id == assistant_id,
        Assistant.workspace_id == workspace_id,
    )
    if for_update:
        statement = statement.with_for_update()
    assistant = (await db.execute(statement)).scalar_one_or_none()
    if assistant is None:
        raise AppError(status_code=404, code="resource_not_found", message="assistant not found")
    return assistant


async def _deployment_for_version(
    db: AsyncSession,
    *,
    deployment_id: str,
    workspace_id: str,
    require_ready_connection: bool,
) -> ModelDeployment:
    deployment = (
        await db.execute(
            select(ModelDeployment)
            .where(ModelDeployment.id == deployment_id, ModelDeployment.workspace_id == workspace_id)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if deployment is None or deployment.status != "active":
        raise AppError(status_code=409, code="deployment_unavailable", message="deployment is not active")
    connection = (
        await db.execute(
            select(ProviderConnection)
            .where(
                ProviderConnection.id == deployment.provider_connection_id,
                ProviderConnection.workspace_id == workspace_id,
            )
            .with_for_update()
        )
    ).scalar_one_or_none()
    if connection is None:
        raise AppError(
            status_code=409,
            code="provider_connection_unavailable",
            message="provider connection is unavailable",
        )
    if require_ready_connection and (
        connection.status != "ready" or not connection.secret_ciphertext
    ):
        raise AppError(
            status_code=409,
            code="provider_connection_unavailable",
            message="provider connection is not ready",
        )
    return deployment


@router.get("")
async def list_assistants(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    statement = select(Assistant).where(Assistant.workspace_id == user.workspace_id)
    if user.role != "admin":
        statement = statement.where(Assistant.default_version_id.is_not(None))
    rows = list((await db.execute(statement.order_by(Assistant.name.asc(), Assistant.id.asc()))).scalars().all())
    return _env({"items": [_assistant_payload(item) for item in rows]})


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_assistant(
    payload: AssistantCreateIn,
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
    _csrf: None = Depends(require_csrf_for_session),
):
    duplicate = (
        await db.execute(
            select(Assistant.id).where(
                Assistant.workspace_id == user.workspace_id,
                Assistant.name == payload.name,
            )
        )
    ).scalar_one_or_none()
    if duplicate is not None:
        raise AppError(status_code=409, code="assistant_conflict", message="assistant name exists")
    assistant = Assistant(
        workspace_id=user.workspace_id,
        name=payload.name,
        description=payload.description.strip() if payload.description else None,
    )
    db.add(assistant)
    await db.flush()
    return _env(_assistant_payload(assistant))


@router.get("/{assistant_id}")
async def get_assistant(
    assistant_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    assistant = await _assistant_for_workspace(db, assistant_id, user.workspace_id)
    if user.role != "admin" and assistant.default_version_id is None:
        raise AppError(status_code=404, code="resource_not_found", message="assistant not found")
    return _env(_assistant_payload(assistant))


@router.patch("/{assistant_id}")
async def patch_assistant(
    assistant_id: str,
    payload: AssistantPatchIn,
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
    _csrf: None = Depends(require_csrf_for_session),
):
    assistant = await _assistant_for_workspace(db, assistant_id, user.workspace_id, for_update=True)
    if assistant.revision != payload.expected_revision:
        raise AppError(
            status_code=409,
            code="config_revision_conflict",
            message="assistant revision changed",
        )
    if payload.name is not None and payload.name != assistant.name:
        duplicate = (
            await db.execute(
                select(Assistant.id).where(
                    Assistant.workspace_id == user.workspace_id,
                    Assistant.name == payload.name,
                    Assistant.id != assistant.id,
                )
            )
        ).scalar_one_or_none()
        if duplicate is not None:
            raise AppError(status_code=409, code="assistant_conflict", message="assistant name exists")
        assistant.name = payload.name
    if payload.description is not None:
        assistant.description = payload.description.strip() or None
    assistant.revision += 1
    await db.flush()
    return _env(_assistant_payload(assistant))


@router.get("/{assistant_id}/versions")
async def list_assistant_versions(
    assistant_id: str,
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    await _assistant_for_workspace(db, assistant_id, user.workspace_id)
    rows = list(
        (
            await db.execute(
                select(AssistantVersion)
                .where(
                    AssistantVersion.assistant_id == assistant_id,
                    AssistantVersion.workspace_id == user.workspace_id,
                )
                .order_by(AssistantVersion.revision.desc())
            )
        ).scalars().all()
    )
    return _env({"items": [_version_payload(item, include_prompt=True) for item in rows]})


@router.post("/{assistant_id}/versions", status_code=status.HTTP_201_CREATED)
async def create_assistant_version(
    assistant_id: str,
    payload: AssistantVersionCreateIn,
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
    _csrf: None = Depends(require_csrf_for_session),
):
    assistant = await _assistant_for_workspace(db, assistant_id, user.workspace_id, for_update=True)
    await _deployment_for_version(
        db,
        deployment_id=payload.deployment_id,
        workspace_id=user.workspace_id,
        require_ready_connection=False,
    )
    policy = (
        await db.execute(
            select(BudgetPolicy).where(
                BudgetPolicy.workspace_id == user.workspace_id,
                BudgetPolicy.is_current.is_(True),
            )
        )
    ).scalar_one_or_none()
    if policy is None or policy.version != payload.policy_version:
        raise AppError(
            status_code=409,
            code="budget_policy_unavailable",
            message="version must use the current approved budget policy",
        )
    latest = await db.scalar(
        select(AssistantVersion.revision)
        .where(AssistantVersion.assistant_id == assistant.id)
        .order_by(AssistantVersion.revision.desc())
        .limit(1)
    )
    version = AssistantVersion(
        workspace_id=user.workspace_id,
        assistant_id=assistant.id,
        deployment_id=payload.deployment_id,
        prompt=payload.prompt,
        policy_version=payload.policy_version,
        revision=int(latest or 0) + 1,
        status="draft",
    )
    db.add(version)
    await db.flush()
    return _env(_version_payload(version, include_prompt=True))


@versions_router.get("/{assistant_version_id}")
async def get_assistant_version(
    assistant_version_id: str,
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    version = await db.get(AssistantVersion, assistant_version_id)
    if version is None or version.workspace_id != user.workspace_id:
        raise AppError(status_code=404, code="resource_not_found", message="assistant version not found")
    return _env(_version_payload(version, include_prompt=True))


@versions_router.post("/{assistant_version_id}/activate")
async def activate_assistant_version(
    assistant_version_id: str,
    payload: RevisionActionIn,
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
    _csrf: None = Depends(require_csrf_for_session),
):
    version = (
        await db.execute(
            select(AssistantVersion)
            .where(
                AssistantVersion.id == assistant_version_id,
                AssistantVersion.workspace_id == user.workspace_id,
            )
            .with_for_update()
        )
    ).scalar_one_or_none()
    if version is None:
        raise AppError(status_code=404, code="resource_not_found", message="assistant version not found")
    if version.revision != payload.expected_revision:
        raise AppError(
            status_code=409,
            code="config_revision_conflict",
            message="assistant version revision changed",
        )
    if version.status == "revoked":
        raise AppError(status_code=409, code="version_revoked", message="revoked version cannot be activated")
    await _deployment_for_version(
        db,
        deployment_id=version.deployment_id,
        workspace_id=user.workspace_id,
        require_ready_connection=True,
    )
    policy = (
        await db.execute(
            select(BudgetPolicy).where(
                BudgetPolicy.workspace_id == user.workspace_id,
                BudgetPolicy.is_current.is_(True),
            )
        )
    ).scalar_one_or_none()
    if policy is None or policy.version != version.policy_version:
        raise AppError(
            status_code=409,
            code="budget_policy_unavailable",
            message="assistant version policy is no longer current",
        )
    version.status = "active"
    version.authorization_epoch += 1
    version.reason = payload.reason
    await db.flush()
    return _env(_version_payload(version, include_prompt=True))


@versions_router.post("/{assistant_version_id}/revoke")
async def revoke_assistant_version(
    assistant_version_id: str,
    payload: RevisionActionIn,
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
    _csrf: None = Depends(require_csrf_for_session),
):
    version = (
        await db.execute(
            select(AssistantVersion)
            .where(
                AssistantVersion.id == assistant_version_id,
                AssistantVersion.workspace_id == user.workspace_id,
            )
            .with_for_update()
        )
    ).scalar_one_or_none()
    if version is None:
        raise AppError(status_code=404, code="resource_not_found", message="assistant version not found")
    if version.revision != payload.expected_revision:
        raise AppError(
            status_code=409,
            code="config_revision_conflict",
            message="assistant version revision changed",
        )
    if version.status == "revoked":
        return _env(_version_payload(version, include_prompt=True))
    version.status = "revoked"
    version.authorization_epoch += 1
    version.reason = payload.reason
    assistant = await _assistant_for_workspace(db, version.assistant_id, user.workspace_id, for_update=True)
    if assistant.default_version_id == version.id:
        assistant.default_version_id = None
        assistant.revision += 1
    await db.flush()
    return _env(_version_payload(version, include_prompt=True))


@router.put("/{assistant_id}/default-version")
async def set_default_assistant_version(
    assistant_id: str,
    payload: DefaultVersionIn,
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
    _csrf: None = Depends(require_csrf_for_session),
):
    assistant = await _assistant_for_workspace(db, assistant_id, user.workspace_id, for_update=True)
    if assistant.revision != payload.expected_revision:
        raise AppError(
            status_code=409,
            code="config_revision_conflict",
            message="assistant revision changed",
        )
    version = await db.get(AssistantVersion, payload.version_id)
    if (
        version is None
        or version.workspace_id != user.workspace_id
        or version.assistant_id != assistant.id
        or version.status != "active"
    ):
        raise AppError(status_code=409, code="version_unavailable", message="version is not active")
    assistant.default_version_id = version.id
    assistant.revision += 1
    await db.flush()
    return _env({**_assistant_payload(assistant), "reason": payload.reason})


@router.post("/{assistant_id}/rollback")
async def rollback_assistant(
    assistant_id: str,
    payload: RollbackIn,
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
    _csrf: None = Depends(require_csrf_for_session),
):
    assistant = await _assistant_for_workspace(db, assistant_id, user.workspace_id, for_update=True)
    if assistant.revision != payload.expected_revision:
        raise AppError(
            status_code=409,
            code="config_revision_conflict",
            message="assistant revision changed",
        )
    problem = (
        await db.execute(
            select(AssistantVersion)
            .where(
                AssistantVersion.id == payload.problem_version_id,
                AssistantVersion.workspace_id == user.workspace_id,
                AssistantVersion.assistant_id == assistant.id,
            )
            .with_for_update()
        )
    ).scalar_one_or_none()
    target = (
        await db.execute(
            select(AssistantVersion)
            .where(
                AssistantVersion.id == payload.target_version_id,
                AssistantVersion.workspace_id == user.workspace_id,
                AssistantVersion.assistant_id == assistant.id,
            )
            .with_for_update()
        )
    ).scalar_one_or_none()
    if (
        problem is None
        or assistant.default_version_id != problem.id
        or target is None
        or target.status != "active"
        or target.id == problem.id
    ):
        raise AppError(status_code=409, code="version_unavailable", message="rollback target is not active")
    assistant.default_version_id = target.id
    assistant.revision += 1
    await db.flush()
    return _env({**_assistant_payload(assistant), "reason": payload.reason})
