from __future__ import annotations

import json
from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import require_admin, require_csrf_for_session
from app.core.db import get_db
from app.core.errors import AppError
from app.core.request_id import get_request_id
from app.core.security import ensure_utc
from app.models import (
    BudgetAccount,
    BudgetPolicy,
    ModelDeployment,
    Operation,
    OperationAttempt,
    User,
    Workspace,
)
from app.schemas import BudgetPolicyPutIn

router = APIRouter()


def _env(payload: object) -> dict[str, object]:
    return {"data": payload, "request_id": get_request_id()}


def _policy_payload(policy: BudgetPolicy) -> dict[str, object]:
    return {
        "id": policy.id,
        "version": policy.version,
        "currency": policy.currency,
        "workspace_daily_limit": str(policy.workspace_daily_limit),
        "workspace_monthly_limit": str(policy.workspace_monthly_limit),
        "conversation_limit": str(policy.conversation_limit),
        "turn_limit": str(policy.turn_limit),
        "max_attempts_per_turn": policy.max_attempts_per_turn,
        "max_input_tokens": policy.max_input_tokens,
        "max_output_tokens": policy.max_output_tokens,
        "reason": policy.reason,
        "created_at": ensure_utc(policy.created_at).isoformat(),
    }


@router.get("/budget-policies/current")
async def get_current_budget_policy(
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    policy = (
        await db.execute(
            select(BudgetPolicy).where(
                BudgetPolicy.workspace_id == user.workspace_id,
                BudgetPolicy.is_current.is_(True),
            )
        )
    ).scalar_one_or_none()
    if policy is None:
        raise AppError(status_code=404, code="resource_not_found", message="budget policy not configured")
    accounts = list(
        (
            await db.execute(
                select(BudgetAccount)
                .where(BudgetAccount.policy_id == policy.id)
                .order_by(BudgetAccount.scope.asc(), BudgetAccount.period_start.asc())
            )
        ).scalars().all()
    )
    snapshots = [
        {
            "scope": account.scope,
            "subject_id": account.subject_id,
            "period_type": account.period_type,
            "period_start": ensure_utc(account.period_start).isoformat(),
            "limit": str(account.limit_amount),
            "spent": str(account.spent_amount),
            "held": str(account.held_amount),
            "available": str(account.limit_amount - account.spent_amount - account.held_amount),
        }
        for account in accounts
    ]
    return _env({**_policy_payload(policy), "accounts": snapshots})


@router.put("/budget-policies/current")
async def put_current_budget_policy(
    payload: BudgetPolicyPutIn,
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
    _csrf: None = Depends(require_csrf_for_session),
):
    workspace = (
        await db.execute(
            select(Workspace).where(Workspace.id == user.workspace_id).with_for_update()
        )
    ).scalar_one_or_none()
    if workspace is None:
        raise AppError(status_code=404, code="workspace_not_found", message="workspace not found")
    current = (
        await db.execute(
            select(BudgetPolicy)
            .where(
                BudgetPolicy.workspace_id == user.workspace_id,
                BudgetPolicy.is_current.is_(True),
            )
            .with_for_update()
        )
    ).scalar_one_or_none()
    actual_revision = current.version if current is not None else 0
    if payload.expected_revision != actual_revision:
        raise AppError(
            status_code=409,
            code="config_revision_conflict",
            message="budget policy revision changed",
            details={"current_revision": actual_revision},
        )
    if current is not None:
        current.is_current = False
    policy = BudgetPolicy(
        workspace_id=user.workspace_id,
        version=actual_revision + 1,
        currency=payload.currency,
        workspace_daily_limit=payload.workspace_daily_limit,
        workspace_monthly_limit=payload.workspace_monthly_limit,
        conversation_limit=payload.conversation_limit,
        turn_limit=payload.turn_limit,
        max_attempts_per_turn=payload.max_attempts_per_turn,
        max_input_tokens=payload.max_input_tokens,
        max_output_tokens=payload.max_output_tokens,
        is_current=True,
        reason=payload.reason,
    )
    db.add(policy)
    await db.flush()
    return _env(_policy_payload(policy))


@router.get("/usage")
async def list_usage(
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
    limit: int = Query(default=20, ge=1, le=100),
    model_id: str | None = Query(default=None, max_length=256),
    status_filter: str | None = Query(default=None, alias="status", max_length=32),
    from_at: datetime | None = Query(default=None, alias="from"),
    to_at: datetime | None = Query(default=None, alias="to"),
):
    if from_at is not None and to_at is not None and ensure_utc(from_at) > ensure_utc(to_at):
        raise AppError(status_code=422, code="validation_error", message="from must be before to")
    statement = (
        select(OperationAttempt, Operation, ModelDeployment)
        .join(Operation, Operation.id == OperationAttempt.operation_id)
        .join(ModelDeployment, ModelDeployment.id == OperationAttempt.deployment_id)
        .where(OperationAttempt.workspace_id == user.workspace_id)
    )
    if model_id:
        statement = statement.where(ModelDeployment.model_id == model_id)
    if status_filter:
        statement = statement.where(OperationAttempt.status == status_filter)
    if from_at is not None:
        statement = statement.where(OperationAttempt.created_at >= ensure_utc(from_at))
    if to_at is not None:
        statement = statement.where(OperationAttempt.created_at <= ensure_utc(to_at))
    rows = list(
        (
            await db.execute(
                statement.order_by(OperationAttempt.created_at.desc(), OperationAttempt.id.desc()).limit(limit)
            )
        ).all()
    )
    items = []
    for attempt, operation, deployment in rows:
        usage = json.loads(attempt.usage_json) if attempt.usage_json else None
        items.append(
            {
                "attempt_id": attempt.id,
                "operation_id": operation.id,
                "operation_kind": operation.kind,
                "run_id": operation.run_id,
                "model_id": deployment.model_id,
                "currency": deployment.currency,
                "status": attempt.status,
                "usage": usage,
                "provider_request_id": attempt.provider_request_id,
                "created_at": ensure_utc(attempt.created_at).isoformat(),
                "settled_at": ensure_utc(attempt.settled_at).isoformat() if attempt.settled_at else None,
            }
        )
    return _env({"items": items})
