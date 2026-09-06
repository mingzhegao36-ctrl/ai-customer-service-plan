from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import ROUND_UP, Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import AsyncSessionFactory
from app.core.errors import AppError
from app.core.security import decrypt_provider_secret, ensure_utc, utc_now
from app.models import (
    AssistantVersion,
    BudgetAccount,
    BudgetLedger,
    BudgetPolicy,
    BudgetReservation,
    Conversation,
    Job,
    ModelDeployment,
    Operation,
    OperationAttempt,
    ProviderConnection,
    ProviderConnectionTest,
    Run,
    Workspace,
    new_uuid,
)
from app.services.provider import ProviderUsage

MILLION = Decimal("1000000")
ACCOUNT_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


@dataclass(frozen=True)
class GenerationDispatch:
    attempt_id: str
    base_url: str
    secret: str
    model_id: str
    system_prompt: str
    max_output_tokens: int


def _money(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.00000001"), rounding=ROUND_UP)


def _estimate_input_tokens(system_prompt: str, user_content: str) -> int:
    return max(1, (len(system_prompt) + len(user_content) + 3) // 4)


def _period_start(now: datetime, timezone_name: str, period_type: str) -> datetime:
    local = ensure_utc(now).astimezone(ZoneInfo(timezone_name))
    if period_type == "daily":
        return datetime(local.year, local.month, local.day, tzinfo=local.tzinfo).astimezone(UTC)
    if period_type == "monthly":
        return datetime(local.year, local.month, 1, tzinfo=local.tzinfo).astimezone(UTC)
    return ACCOUNT_EPOCH


async def _insert_account_if_missing(
    db: AsyncSession,
    values: dict[str, object],
) -> None:
    dialect = db.bind.dialect.name if db.bind is not None else ""
    if dialect == "postgresql":
        await db.execute(
            postgresql_insert(BudgetAccount)
            .values(**values)
            .on_conflict_do_nothing(
                constraint="uq_budget_account_scope_period",
            )
        )
    elif dialect == "sqlite":
        await db.execute(
            sqlite_insert(BudgetAccount)
            .values(**values)
            .on_conflict_do_nothing(
                index_elements=[
                    "workspace_id",
                    "policy_id",
                    "scope",
                    "subject_id",
                    "period_type",
                    "period_start",
                    "currency",
                ]
            )
        )
    else:
        existing = (
            await db.execute(
                select(BudgetAccount).where(
                    BudgetAccount.workspace_id == values["workspace_id"],
                    BudgetAccount.policy_id == values["policy_id"],
                    BudgetAccount.scope == values["scope"],
                    BudgetAccount.subject_id == values["subject_id"],
                    BudgetAccount.period_type == values["period_type"],
                    BudgetAccount.period_start == values["period_start"],
                    BudgetAccount.currency == values["currency"],
                )
            )
        ).scalar_one_or_none()
        if existing is None:
            db.add(BudgetAccount(**values))
            await db.flush()


def _account_specs(
    *,
    policy: BudgetPolicy,
    workspace: Workspace,
    conversation: Conversation,
    run: Run,
    now: datetime,
) -> list[tuple[str, str, str, datetime, Decimal]]:
    return [
        (
            "conversation",
            conversation.id,
            "lifetime",
            ACCOUNT_EPOCH,
            policy.conversation_limit,
        ),
        ("turn", run.turn_id, "lifetime", ACCOUNT_EPOCH, policy.turn_limit),
        (
            "workspace_daily",
            workspace.id,
            "daily",
            _period_start(now, workspace.timezone, "daily"),
            policy.workspace_daily_limit,
        ),
        (
            "workspace_monthly",
            workspace.id,
            "monthly",
            _period_start(now, workspace.timezone, "monthly"),
            policy.workspace_monthly_limit,
        ),
    ]


async def reserve_generation(
    db: AsyncSession,
    *,
    run_id: str,
    user_content: str,
) -> GenerationDispatch:
    run_snapshot = (await db.execute(select(Run).where(Run.id == run_id))).scalar_one_or_none()
    if run_snapshot is None or not run_snapshot.assistant_version_id:
        raise AppError(status_code=409, code="run_not_dispatchable", message="run is not dispatchable")
    conversation_snapshot = await db.get(Conversation, run_snapshot.conversation_id)
    if conversation_snapshot is None:
        raise AppError(status_code=409, code="run_not_dispatchable", message="conversation is unavailable")
    workspace = (
        await db.execute(
            select(Workspace).where(Workspace.id == conversation_snapshot.workspace_id).with_for_update()
        )
    ).scalar_one_or_none()
    if workspace is None or workspace.service_mode != "open":
        raise AppError(status_code=409, code="service_paused", message="AI service is currently closed")
    version = (
        await db.execute(
            select(AssistantVersion)
            .where(
                AssistantVersion.id == run_snapshot.assistant_version_id,
                AssistantVersion.workspace_id == workspace.id,
            )
            .with_for_update()
        )
    ).scalar_one_or_none()
    if version is None or version.status != "active":
        raise AppError(
            status_code=409,
            code="assistant_version_unavailable",
            message="assistant version is not active",
        )
    deployment = (
        await db.execute(
            select(ModelDeployment)
            .where(
                ModelDeployment.id == version.deployment_id,
                ModelDeployment.workspace_id == workspace.id,
            )
            .with_for_update()
        )
    ).scalar_one_or_none()
    if deployment is None or deployment.status != "active":
        raise AppError(
            status_code=409,
            code="deployment_unavailable",
            message="model deployment is not active",
        )
    connection = (
        await db.execute(
            select(ProviderConnection)
            .where(
                ProviderConnection.id == deployment.provider_connection_id,
                ProviderConnection.workspace_id == workspace.id,
            )
            .with_for_update()
        )
    ).scalar_one_or_none()
    if connection is None or connection.status != "ready" or not connection.secret_ciphertext:
        raise AppError(
            status_code=409,
            code="provider_connection_unavailable",
            message="provider connection is not ready",
        )
    policy = (
        await db.execute(
            select(BudgetPolicy)
            .where(BudgetPolicy.workspace_id == workspace.id, BudgetPolicy.is_current.is_(True))
            .with_for_update()
        )
    ).scalar_one_or_none()
    if policy is None:
        raise AppError(
            status_code=409,
            code="budget_policy_missing",
            message="an approved budget policy is required before provider dispatch",
        )
    if policy.version != version.policy_version or policy.currency != deployment.currency:
        raise AppError(
            status_code=409,
            code="budget_policy_unavailable",
            message="assistant version does not match the current budget policy",
        )
    conversation = (
        await db.execute(
            select(Conversation).where(Conversation.id == conversation_snapshot.id).with_for_update()
        )
    ).scalar_one_or_none()
    run = (await db.execute(select(Run).where(Run.id == run_id).with_for_update())).scalar_one_or_none()
    if (
        conversation is None
        or conversation.deleted_at is not None
        or conversation.workspace_id != workspace.id
        or run is None
        or run.status != "running"
        or run.conversation_id != conversation.id
        or run.assistant_version_id != version.id
    ):
        raise AppError(status_code=409, code="run_not_dispatchable", message="run is not dispatchable")
    input_tokens = _estimate_input_tokens(version.prompt, user_content)
    if input_tokens > min(policy.max_input_tokens, deployment.max_input_tokens):
        raise AppError(status_code=413, code="input_too_large", message="provider input limit exceeded")
    max_output = min(policy.max_output_tokens, deployment.max_output_tokens)
    reserved_amount = _money(
        (
            Decimal(input_tokens) * deployment.input_price_per_million
            + Decimal(max_output) * deployment.output_price_per_million
        )
        / MILLION
    )
    used_attempts = await db.scalar(
        select(func.count(OperationAttempt.id))
        .join(Operation, Operation.id == OperationAttempt.operation_id)
        .join(Run, Run.id == Operation.run_id)
        .where(Run.conversation_id == conversation.id, Run.turn_id == run.turn_id)
    )
    if int(used_attempts or 0) >= policy.max_attempts_per_turn:
        raise AppError(status_code=429, code="attempt_limit_exceeded", message="turn attempt limit exceeded")
    now = utc_now()
    specs = _account_specs(
        policy=policy,
        workspace=workspace,
        conversation=conversation,
        run=run,
        now=now,
    )
    for scope, subject_id, period_type, period_start, limit_amount in specs:
        await _insert_account_if_missing(
            db,
            {
                "id": new_uuid(),
                "workspace_id": workspace.id,
                "policy_id": policy.id,
                "scope": scope,
                "subject_id": subject_id,
                "period_type": period_type,
                "period_start": period_start,
                "currency": policy.currency,
                "limit_amount": limit_amount,
                "spent_amount": Decimal("0"),
                "held_amount": Decimal("0"),
                "revision": 1,
                "updated_at": now,
            },
        )
    accounts = list(
        (
            await db.execute(
                select(BudgetAccount)
                .where(
                    BudgetAccount.workspace_id == workspace.id,
                    BudgetAccount.policy_id == policy.id,
                    BudgetAccount.currency == policy.currency,
                    BudgetAccount.id.in_(
                        select(BudgetAccount.id).where(
                            BudgetAccount.workspace_id == workspace.id,
                            BudgetAccount.policy_id == policy.id,
                            BudgetAccount.currency == policy.currency,
                            BudgetAccount.subject_id.in_([item[1] for item in specs]),
                        )
                    ),
                )
                .with_for_update()
                .order_by(BudgetAccount.scope.asc(), BudgetAccount.subject_id.asc())
            )
        ).scalars().all()
    )
    expected_keys = {(scope, subject_id, period_type, period_start) for scope, subject_id, period_type, period_start, _ in specs}
    accounts = [
        account
        for account in accounts
        if (account.scope, account.subject_id, account.period_type, ensure_utc(account.period_start))
        in expected_keys
    ]
    if len(accounts) != len(specs):
        raise AppError(status_code=503, code="budget_account_unavailable", message="budget account setup failed")
    if any(account.limit_amount - account.spent_amount - account.held_amount < reserved_amount for account in accounts):
        raise AppError(status_code=429, code="budget_exceeded", message="budget limit would be exceeded")
    existing_operation = (
        await db.execute(select(Operation).where(Operation.run_id == run.id).with_for_update())
    ).scalar_one_or_none()
    if existing_operation is not None:
        raise AppError(
            status_code=409,
            code="run_dispatch_in_progress",
            message="run already has a provider dispatch record",
            retryable=True,
        )

    operation = Operation(
        workspace_id=workspace.id,
        actor_id=conversation.owner_id,
        run_id=run.id,
        kind="generation",
        status="dispatched",
    )
    db.add(operation)
    await db.flush()
    attempt = OperationAttempt(
        workspace_id=workspace.id,
        operation_id=operation.id,
        deployment_id=deployment.id,
        provider_connection_id=connection.id,
        connection_revision=connection.revision,
        number=1,
        status="dispatched",
    )
    db.add(attempt)
    await db.flush()
    for account in accounts:
        account.held_amount += reserved_amount
        account.revision += 1
        db.add(
            BudgetReservation(
                workspace_id=workspace.id,
                attempt_id=attempt.id,
                account_id=account.id,
                currency=policy.currency,
                reserved_amount=reserved_amount,
                status="reserved",
            )
        )
        db.add(
            BudgetLedger(
                workspace_id=workspace.id,
                account_id=account.id,
                attempt_id=attempt.id,
                event_key=f"{attempt.id}:reserve",
                event_type="reserve",
                spent_delta=Decimal("0"),
                held_delta=reserved_amount,
                currency=policy.currency,
            )
        )
    try:
        secret = decrypt_provider_secret(connection.secret_ciphertext)
    except ValueError as exc:
        raise AppError(
            status_code=503,
            code="provider_secret_unavailable",
            message="provider secret cannot be used",
        ) from exc
    return GenerationDispatch(
        attempt_id=attempt.id,
        base_url=connection.base_url,
        secret=secret,
        model_id=deployment.model_id,
        system_prompt=version.prompt,
        max_output_tokens=max_output,
    )


async def reserve_provider_connection_test(
    db: AsyncSession,
    *,
    job_id: str,
) -> GenerationDispatch:
    existing_operation = (
        await db.execute(select(Operation).where(Operation.job_id == job_id))
    ).scalar_one_or_none()
    if existing_operation is not None:
        raise AppError(
            status_code=409,
            code="provider_test_already_dispatched",
            message="provider test already has a dispatch record",
        )
    job = (await db.execute(select(Job).where(Job.id == job_id).with_for_update())).scalar_one_or_none()
    if job is None:
        raise AppError(status_code=404, code="resource_not_found", message="provider test job not found")
    test = (
        await db.execute(
            select(ProviderConnectionTest).where(ProviderConnectionTest.job_id == job_id).with_for_update()
        )
    ).scalar_one_or_none()
    if test is None:
        raise AppError(status_code=404, code="resource_not_found", message="provider test not found")
    if job.workspace_id != test.workspace_id:
        raise AppError(status_code=409, code="provider_test_invalid", message="provider test workspace changed")
    connection = (
        await db.execute(
            select(ProviderConnection)
            .where(
                ProviderConnection.id == test.provider_connection_id,
                ProviderConnection.workspace_id == test.workspace_id,
            )
            .with_for_update()
        )
    ).scalar_one_or_none()
    if (
        connection is None
        or connection.revision != test.expected_revision
        or not connection.secret_ciphertext
    ):
        raise AppError(
            status_code=409,
            code="provider_connection_changed",
            message="provider connection changed before test dispatch",
        )
    deployment = (
        await db.execute(
            select(ModelDeployment)
            .where(
                ModelDeployment.provider_connection_id == connection.id,
                ModelDeployment.workspace_id == test.workspace_id,
                ModelDeployment.revision == connection.revision,
                ModelDeployment.status == "active",
            )
            .order_by(ModelDeployment.model_id.asc())
            .limit(1)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if deployment is None:
        raise AppError(
            status_code=409,
            code="deployment_unavailable",
            message="provider test requires an active deployment",
        )
    workspace = (
        await db.execute(select(Workspace).where(Workspace.id == test.workspace_id).with_for_update())
    ).scalar_one_or_none()
    policy = (
        await db.execute(
            select(BudgetPolicy)
            .where(BudgetPolicy.workspace_id == test.workspace_id, BudgetPolicy.is_current.is_(True))
            .with_for_update()
        )
    ).scalar_one_or_none()
    if workspace is None or policy is None or policy.currency != deployment.currency:
        raise AppError(
            status_code=409,
            code="budget_policy_missing",
            message="provider test requires a current budget policy in the deployment currency",
        )
    max_output = min(1, policy.max_output_tokens, deployment.max_output_tokens)
    reserved_amount = _money(
        (Decimal(16) * deployment.input_price_per_million + Decimal(max_output) * deployment.output_price_per_million)
        / MILLION
    )
    now = utc_now()
    specs = [
        (
            "workspace_daily",
            workspace.id,
            "daily",
            _period_start(now, workspace.timezone, "daily"),
            policy.workspace_daily_limit,
        ),
        (
            "workspace_monthly",
            workspace.id,
            "monthly",
            _period_start(now, workspace.timezone, "monthly"),
            policy.workspace_monthly_limit,
        ),
    ]
    for scope, subject_id, period_type, period_start, limit_amount in specs:
        await _insert_account_if_missing(
            db,
            {
                "id": new_uuid(),
                "workspace_id": workspace.id,
                "policy_id": policy.id,
                "scope": scope,
                "subject_id": subject_id,
                "period_type": period_type,
                "period_start": period_start,
                "currency": policy.currency,
                "limit_amount": limit_amount,
                "spent_amount": Decimal("0"),
                "held_amount": Decimal("0"),
                "revision": 1,
                "updated_at": now,
            },
        )
    accounts = list(
        (
            await db.execute(
                select(BudgetAccount)
                .where(
                    BudgetAccount.workspace_id == workspace.id,
                    BudgetAccount.policy_id == policy.id,
                    BudgetAccount.subject_id == workspace.id,
                    BudgetAccount.currency == policy.currency,
                    BudgetAccount.scope.in_(["workspace_daily", "workspace_monthly"]),
                )
                .with_for_update()
                .order_by(BudgetAccount.scope.asc())
            )
        ).scalars().all()
    )
    if len(accounts) != len(specs) or any(
        account.limit_amount - account.spent_amount - account.held_amount < reserved_amount
        for account in accounts
    ):
        raise AppError(status_code=429, code="budget_exceeded", message="provider test budget exceeded")
    operation = Operation(
        workspace_id=workspace.id,
        actor_id=job.actor_id,
        job_id=job_id,
        kind="provider_connection_test",
        status="dispatched",
    )
    db.add(operation)
    await db.flush()
    attempt = OperationAttempt(
        workspace_id=workspace.id,
        operation_id=operation.id,
        deployment_id=deployment.id,
        provider_connection_id=connection.id,
        connection_revision=connection.revision,
        number=1,
        status="dispatched",
    )
    db.add(attempt)
    await db.flush()
    for account in accounts:
        account.held_amount += reserved_amount
        account.revision += 1
        db.add(
            BudgetReservation(
                workspace_id=workspace.id,
                attempt_id=attempt.id,
                account_id=account.id,
                currency=policy.currency,
                reserved_amount=reserved_amount,
                status="reserved",
            )
        )
        db.add(
            BudgetLedger(
                workspace_id=workspace.id,
                account_id=account.id,
                attempt_id=attempt.id,
                event_key=f"{attempt.id}:reserve",
                event_type="reserve",
                spent_delta=Decimal("0"),
                held_delta=reserved_amount,
                currency=policy.currency,
            )
        )
    try:
        secret = decrypt_provider_secret(connection.secret_ciphertext)
    except ValueError as exc:
        raise AppError(
            status_code=503,
            code="provider_secret_unavailable",
            message="provider secret cannot be used",
        ) from exc
    return GenerationDispatch(
        attempt_id=attempt.id,
        base_url=connection.base_url,
        secret=secret,
        model_id=deployment.model_id,
        system_prompt="Reply only with OK to verify this approved provider connection.",
        max_output_tokens=max_output,
    )


def _actual_amount(
    *,
    attempt: OperationAttempt,
    deployment: ModelDeployment,
    usage: ProviderUsage,
    reserved_amount: Decimal,
) -> tuple[Decimal, str]:
    if usage.input_tokens is None or usage.output_tokens is None:
        return reserved_amount, "estimated"
    amount = _money(
        (
            Decimal(usage.input_tokens) * deployment.input_price_per_million
            + Decimal(usage.output_tokens) * deployment.output_price_per_million
        )
        / MILLION
    )
    return amount, "actual"


async def settle_generation(attempt_id: str, usage: ProviderUsage) -> None:
    async with AsyncSessionFactory() as db:
        attempt = (
            await db.execute(select(OperationAttempt).where(OperationAttempt.id == attempt_id).with_for_update())
        ).scalar_one_or_none()
        if attempt is None or attempt.status != "dispatched":
            await db.rollback()
            return
        deployment = await db.get(ModelDeployment, attempt.deployment_id)
        reservations = list(
            (
                await db.execute(
                    select(BudgetReservation)
                    .where(BudgetReservation.attempt_id == attempt.id)
                    .with_for_update()
                )
            ).scalars().all()
        )
        if deployment is None or not reservations:
            await db.rollback()
            return
        accounts = list(
            (
                await db.execute(
                    select(BudgetAccount)
                    .where(BudgetAccount.id.in_([item.account_id for item in reservations]))
                    .with_for_update()
                    .order_by(BudgetAccount.id.asc())
                )
            ).scalars().all()
        )
        account_by_id = {account.id: account for account in accounts}
        actual_amount, quality = _actual_amount(
            attempt=attempt,
            deployment=deployment,
            usage=usage,
            reserved_amount=reservations[0].reserved_amount,
        )
        now = utc_now()
        for reservation in reservations:
            account = account_by_id.get(reservation.account_id)
            if account is None:
                await db.rollback()
                return
            account.held_amount -= reservation.reserved_amount
            account.spent_amount += actual_amount
            account.revision += 1
            reservation.status = "settled"
            reservation.actual_amount = actual_amount
            reservation.settled_at = now
            db.add(
                BudgetLedger(
                    workspace_id=attempt.workspace_id,
                    account_id=account.id,
                    attempt_id=attempt.id,
                    event_key=f"{attempt.id}:settle",
                    event_type="settle",
                    spent_delta=actual_amount,
                    held_delta=-reservation.reserved_amount,
                    currency=reservation.currency,
                )
            )
        attempt.status = "completed"
        attempt.provider_request_id = usage.provider_request_id
        attempt.usage_json = json.dumps(
            {
                "input_tokens": usage.input_tokens,
                "output_tokens": usage.output_tokens,
                "quality": quality,
            }
        )
        attempt.settled_at = now
        operation = await db.get(Operation, attempt.operation_id)
        if operation is not None:
            operation.status = "settled"
        await db.commit()


async def mark_generation_failed(
    attempt_id: str,
    *,
    error_code: str,
    outcome_unknown: bool,
) -> None:
    async with AsyncSessionFactory() as db:
        attempt = (
            await db.execute(select(OperationAttempt).where(OperationAttempt.id == attempt_id).with_for_update())
        ).scalar_one_or_none()
        if attempt is None or attempt.status != "dispatched":
            await db.rollback()
            return
        operation = await db.get(Operation, attempt.operation_id)
        if outcome_unknown:
            attempt.status = "unknown"
            attempt.error_code = error_code
            if operation is not None:
                operation.status = "unknown"
            await db.commit()
            return
        reservations = list(
            (
                await db.execute(
                    select(BudgetReservation)
                    .where(BudgetReservation.attempt_id == attempt.id)
                    .with_for_update()
                )
            ).scalars().all()
        )
        accounts = list(
            (
                await db.execute(
                    select(BudgetAccount)
                    .where(BudgetAccount.id.in_([item.account_id for item in reservations]))
                    .with_for_update()
                    .order_by(BudgetAccount.id.asc())
                )
            ).scalars().all()
        )
        account_by_id = {account.id: account for account in accounts}
        now = utc_now()
        for reservation in reservations:
            account = account_by_id.get(reservation.account_id)
            if account is None:
                await db.rollback()
                return
            account.held_amount -= reservation.reserved_amount
            account.revision += 1
            reservation.status = "voided"
            reservation.actual_amount = Decimal("0")
            reservation.settled_at = now
            db.add(
                BudgetLedger(
                    workspace_id=attempt.workspace_id,
                    account_id=account.id,
                    attempt_id=attempt.id,
                    event_key=f"{attempt.id}:void",
                    event_type="void",
                    spent_delta=Decimal("0"),
                    held_delta=-reservation.reserved_amount,
                    currency=reservation.currency,
                )
            )
        attempt.status = "voided"
        attempt.error_code = error_code
        attempt.settled_at = now
        if operation is not None:
            operation.status = "voided"
        await db.commit()
