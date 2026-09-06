from __future__ import annotations

import json

from fastapi import APIRouter, Depends, Header, Query, status
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import require_admin, require_csrf_for_session
from app.api.v1.endpoints.conversations import (
    _claim_idempotency,
    _json_response,
    _replay_idempotency,
)
from app.core.db import get_db
from app.core.errors import AppError
from app.core.request_id import get_request_id
from app.core.security import (
    encrypt_provider_secret,
    provider_secret_hint,
    request_digest,
)
from app.models import (
    Job,
    ModelDeployment,
    ProviderConnection,
    ProviderConnectionTest,
    User,
)
from app.schemas import (
    ProviderConnectionCreateIn,
    ProviderConnectionPatchIn,
    ProviderConnectionTestIn,
)
from app.services.provider import validate_provider_base_url

router = APIRouter(prefix="/provider-connections")


def _env(payload: object) -> dict[str, object]:
    return {"data": payload, "request_id": get_request_id()}


def _deployment_payload(item: ModelDeployment) -> dict[str, object]:
    return {
        "id": item.id,
        "model_id": item.model_id,
        "currency": item.currency,
        "input_price_per_million": str(item.input_price_per_million),
        "output_price_per_million": str(item.output_price_per_million),
        "max_input_tokens": item.max_input_tokens,
        "max_output_tokens": item.max_output_tokens,
        "revision": item.revision,
        "status": item.status,
    }


async def _connection_payload(db: AsyncSession, connection: ProviderConnection) -> dict[str, object]:
    deployments = list(
        (
            await db.execute(
                select(ModelDeployment)
                .where(
                    ModelDeployment.provider_connection_id == connection.id,
                    ModelDeployment.revision == connection.revision,
                )
                .order_by(ModelDeployment.model_id.asc())
            )
        ).scalars().all()
    )
    return {
        "id": connection.id,
        "name": connection.name,
        "provider": connection.provider,
        "base_url": connection.base_url,
        "secret_configured": connection.secret_ciphertext is not None,
        "secret_hint": connection.secret_hint,
        "capabilities": json.loads(connection.capabilities_json),
        "revision": connection.revision,
        "status": connection.status,
        "last_tested_at": connection.last_tested_at.isoformat() if connection.last_tested_at else None,
        "deployments": [_deployment_payload(item) for item in deployments],
    }


def _validate_deployments(payload: ProviderConnectionCreateIn | ProviderConnectionPatchIn) -> None:
    if payload.deployments is None:
        return
    model_ids = [item.model_id for item in payload.deployments]
    if len(set(model_ids)) != len(model_ids):
        raise AppError(status_code=422, code="validation_error", message="model_id must be unique")


async def _add_deployments(
    db: AsyncSession,
    *,
    connection: ProviderConnection,
    revision: int,
    deployments: list,
) -> None:
    for item in deployments:
        db.add(
            ModelDeployment(
                workspace_id=connection.workspace_id,
                provider_connection_id=connection.id,
                model_id=item.model_id,
                currency=item.currency,
                input_price_per_million=item.input_price_per_million,
                output_price_per_million=item.output_price_per_million,
                max_input_tokens=item.max_input_tokens,
                max_output_tokens=item.max_output_tokens,
                revision=revision,
                status="active",
            )
        )


@router.get("")
async def list_provider_connections(
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
    limit: int = Query(default=20, ge=1, le=100),
):
    rows = list(
        (
            await db.execute(
                select(ProviderConnection)
                .where(ProviderConnection.workspace_id == user.workspace_id)
                .order_by(ProviderConnection.created_at.desc(), ProviderConnection.id.desc())
                .limit(limit)
            )
        ).scalars().all()
    )
    return _env({"items": [await _connection_payload(db, item) for item in rows]})


@router.get("/{provider_connection_id}")
async def get_provider_connection(
    provider_connection_id: str,
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    connection = await db.get(ProviderConnection, provider_connection_id)
    if connection is None or connection.workspace_id != user.workspace_id:
        raise AppError(status_code=404, code="resource_not_found", message="provider connection not found")
    return _env(await _connection_payload(db, connection))


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_provider_connection(
    payload: ProviderConnectionCreateIn,
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
    _csrf: None = Depends(require_csrf_for_session),
):
    _validate_deployments(payload)
    try:
        base_url = await validate_provider_base_url(payload.base_url)
    except ValueError as exc:
        raise AppError(status_code=422, code="provider_url_invalid", message=str(exc)) from None
    duplicate = (
        await db.execute(
            select(ProviderConnection.id).where(
                ProviderConnection.workspace_id == user.workspace_id,
                ProviderConnection.name == payload.name,
            )
        )
    ).scalar_one_or_none()
    if duplicate is not None:
        raise AppError(status_code=409, code="provider_connection_conflict", message="connection name exists")
    connection = ProviderConnection(
        workspace_id=user.workspace_id,
        name=payload.name,
        provider=payload.provider,
        base_url=base_url,
        secret_ciphertext=encrypt_provider_secret(payload.secret),
        secret_hint=provider_secret_hint(payload.secret),
        capabilities_json=json.dumps({"chat_completions": True, "streaming": True}),
        revision=1,
        status="draft",
    )
    db.add(connection)
    await db.flush()
    await _add_deployments(db, connection=connection, revision=connection.revision, deployments=payload.deployments)
    await db.flush()
    return _env(await _connection_payload(db, connection))


@router.patch("/{provider_connection_id}")
async def patch_provider_connection(
    provider_connection_id: str,
    payload: ProviderConnectionPatchIn,
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
    _csrf: None = Depends(require_csrf_for_session),
):
    _validate_deployments(payload)
    connection = (
        await db.execute(
            select(ProviderConnection)
            .where(
                ProviderConnection.id == provider_connection_id,
                ProviderConnection.workspace_id == user.workspace_id,
            )
            .with_for_update()
        )
    ).scalar_one_or_none()
    if connection is None:
        raise AppError(status_code=404, code="resource_not_found", message="provider connection not found")
    if connection.revision != payload.expected_revision:
        raise AppError(
            status_code=409,
            code="config_revision_conflict",
            message="provider connection revision changed",
        )
    if payload.name is not None and payload.name != connection.name:
        duplicate = (
            await db.execute(
                select(ProviderConnection.id).where(
                    ProviderConnection.workspace_id == user.workspace_id,
                    ProviderConnection.name == payload.name,
                    ProviderConnection.id != connection.id,
                )
            )
        ).scalar_one_or_none()
        if duplicate is not None:
            raise AppError(status_code=409, code="provider_connection_conflict", message="connection name exists")
        connection.name = payload.name
    configuration_changed = any(
        value is not None for value in (payload.base_url, payload.secret, payload.deployments)
    )
    if payload.base_url is not None:
        try:
            connection.base_url = await validate_provider_base_url(payload.base_url)
        except ValueError as exc:
            raise AppError(status_code=422, code="provider_url_invalid", message=str(exc)) from None
    if payload.secret is not None:
        connection.secret_ciphertext = encrypt_provider_secret(payload.secret)
        connection.secret_hint = provider_secret_hint(payload.secret)
    if configuration_changed:
        old_deployments = list(
            (
                await db.execute(
                    select(ModelDeployment).where(
                        ModelDeployment.provider_connection_id == connection.id,
                        ModelDeployment.revision == connection.revision,
                    )
                )
            ).scalars().all()
        )
        connection.revision += 1
        connection.status = "draft"
        connection.last_tested_at = None
        await db.execute(
            update(ModelDeployment)
            .where(ModelDeployment.provider_connection_id == connection.id)
            .values(status="revoked")
        )
        if payload.deployments is not None:
            await _add_deployments(
                db,
                connection=connection,
                revision=connection.revision,
                deployments=payload.deployments,
            )
        else:
            for old in old_deployments:
                db.add(
                    ModelDeployment(
                        workspace_id=connection.workspace_id,
                        provider_connection_id=connection.id,
                        model_id=old.model_id,
                        currency=old.currency,
                        input_price_per_million=old.input_price_per_million,
                        output_price_per_million=old.output_price_per_million,
                        max_input_tokens=old.max_input_tokens,
                        max_output_tokens=old.max_output_tokens,
                        revision=connection.revision,
                        status="active",
                    )
                )
    await db.flush()
    return _env(await _connection_payload(db, connection))


@router.delete("/{provider_connection_id}/secret", status_code=status.HTTP_204_NO_CONTENT)
async def delete_provider_secret(
    provider_connection_id: str,
    expected_revision: int = Query(ge=1),
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
    _csrf: None = Depends(require_csrf_for_session),
):
    connection = (
        await db.execute(
            select(ProviderConnection)
            .where(
                ProviderConnection.id == provider_connection_id,
                ProviderConnection.workspace_id == user.workspace_id,
            )
            .with_for_update()
        )
    ).scalar_one_or_none()
    if connection is None:
        raise AppError(status_code=404, code="resource_not_found", message="provider connection not found")
    if connection.revision != expected_revision:
        raise AppError(
            status_code=409,
            code="config_revision_conflict",
            message="provider connection revision changed",
        )
    connection.secret_ciphertext = None
    connection.secret_hint = None
    connection.status = "revoked"
    connection.revision += 1
    await db.execute(
        update(ModelDeployment)
        .where(ModelDeployment.provider_connection_id == connection.id)
        .values(status="revoked")
    )
    return None


@router.post("/{provider_connection_id}/test", status_code=status.HTTP_202_ACCEPTED)
async def test_provider_connection(
    provider_connection_id: str,
    payload: ProviderConnectionTestIn,
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
    _csrf: None = Depends(require_csrf_for_session),
    idempotency_key: str = Header(alias="Idempotency-Key", min_length=1, max_length=128),
):
    digest = request_digest(payload.model_dump())
    record, claimed = await _claim_idempotency(
        db,
        workspace_id=user.workspace_id,
        actor_id=user.id,
        method="POST",
        resource=f"/provider-connections/{provider_connection_id}/test",
        key=idempotency_key,
        digest=digest,
    )
    if not claimed:
        return _replay_idempotency(record)
    connection = (
        await db.execute(
            select(ProviderConnection).where(
                ProviderConnection.id == provider_connection_id,
                ProviderConnection.workspace_id == user.workspace_id,
            )
        )
    ).scalar_one_or_none()
    if connection is None:
        raise AppError(status_code=404, code="resource_not_found", message="provider connection not found")
    if connection.revision != payload.expected_revision or not connection.secret_ciphertext:
        raise AppError(
            status_code=409,
            code="config_revision_conflict",
            message="provider connection is not ready for this test",
        )
    job = Job(
        workspace_id=user.workspace_id,
        actor_id=user.id,
        type="provider_connection_test",
        status="queued",
        stage="provider_test_queued",
        resource_type="provider_connection",
        resource_id=connection.id,
        retryable=True,
    )
    db.add(job)
    await db.flush()
    db.add(
        ProviderConnectionTest(
            workspace_id=user.workspace_id,
            provider_connection_id=connection.id,
            job_id=job.id,
            expected_revision=connection.revision,
            status="queued",
        )
    )
    result = {"job_id": job.id, "status": "queued"}
    record.status_code = status.HTTP_202_ACCEPTED
    record.response_json = json.dumps(result)
    return _json_response(result, status.HTTP_202_ACCEPTED)
