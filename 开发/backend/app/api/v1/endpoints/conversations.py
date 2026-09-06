from __future__ import annotations

import asyncio
import json
from datetime import datetime
from uuid import NAMESPACE_URL, uuid5

from fastapi import APIRouter, Depends, Header, Query, Response, status
from fastapi.responses import JSONResponse, StreamingResponse
from sqlalchemy import and_, or_, select, update
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import get_current_user, require_csrf_for_session
from app.core.config import settings
from app.core.db import AsyncSessionFactory, get_db
from app.core.errors import AppError
from app.core.journal_db import JournalSessionFactory
from app.core.request_id import get_request_id
from app.core.security import (
    decode_cursor,
    encode_cursor,
    ensure_utc,
    request_digest,
    utc_now,
)
from app.deletion_recovery import DeletionRecoveryError, recover_deletion_journal
from app.journal_models import DeletionJournal, JournalHead
from app.models import (
    Assistant,
    AssistantVersion,
    Conversation,
    DeletionIntent,
    DeletionReceipt,
    IdempotencyRecord,
    Job,
    Message,
    Run,
    User,
    Workspace,
    new_uuid,
)
from app.schemas import ConversationCreateIn, ConversationPatchIn, MessageCreateIn
from app.services.billing import (
    mark_generation_failed,
    reserve_generation,
    settle_generation,
)
from app.services.provider import (
    ProviderError,
    ProviderUsage,
    complete,
    stream_completion,
)

router = APIRouter(prefix="/conversations")
runs_router = APIRouter(prefix="/runs")


def _env(payload: object) -> dict[str, object]:
    return {"data": payload, "request_id": get_request_id()}


def _json_response(payload: object, status_code: int = 200) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content=_env(payload),
        headers={"Cache-Control": "no-store", "X-Request-ID": get_request_id()},
    )


def _conversation_payload(conversation: Conversation) -> dict[str, object]:
    return {
        "id": conversation.id,
        "assistant_id": conversation.assistant_id,
        "current_assistant_version_id": conversation.current_assistant_version_id,
        "subject": conversation.subject,
        "status": conversation.status,
        "revision": conversation.revision,
        "write_epoch": conversation.run_epoch,
        "turn_count": conversation.turn_count,
        "valid_reply_count": conversation.valid_reply_count,
        "active_answer_id": conversation.active_answer_id,
        "last_activity_at": (
            ensure_utc(conversation.last_activity_at).isoformat()
            if conversation.last_activity_at
            else None
        ),
        "created_at": ensure_utc(conversation.created_at).isoformat(),
    }


def _run_snapshot(
    conversation: Conversation,
    run: Run,
    *,
    replayed: bool,
) -> dict[str, object]:
    return {
        "conversation_id": conversation.id,
        "turn_id": run.turn_id,
        "run_id": run.id,
        "status": run.status,
        "error": run.error_code,
        "active_answer_id": conversation.active_answer_id,
        "conversation_revision": conversation.revision,
        "write_epoch": run.write_epoch,
        "visible_content_version": run.visible_content_version,
        "published_seq": run.published_seq,
        "visible_text": run.answer_text or "",
        "is_complete": run.status in {"completed", "failed", "cancelled"},
        "replayed": replayed,
    }


async def _resolve_conversation(
    db: AsyncSession,
    user: User,
    conversation_id: str,
    *,
    for_update: bool = False,
) -> Conversation:
    statement = select(Conversation).where(
        Conversation.id == conversation_id,
        Conversation.workspace_id == user.workspace_id,
        Conversation.owner_id == user.id,
        Conversation.deleted_at.is_(None),
    )
    if for_update:
        statement = statement.with_for_update()
    conversation = (await db.execute(statement)).scalar_one_or_none()
    if conversation is None:
        raise AppError(
            status_code=404,
            code="resource_not_found",
            message="conversation not found",
        )
    return conversation


async def _claim_idempotency(
    db: AsyncSession,
    *,
    workspace_id: str,
    actor_id: str,
    method: str,
    resource: str,
    key: str,
    digest: str,
) -> tuple[IdempotencyRecord, bool]:
    query = select(IdempotencyRecord).where(
        IdempotencyRecord.workspace_id == workspace_id,
        IdempotencyRecord.actor_id == actor_id,
        IdempotencyRecord.method == method,
        IdempotencyRecord.resource == resource,
        IdempotencyRecord.idempotency_key == key,
    )
    existing = (await db.execute(query)).scalar_one_or_none()
    if existing is not None:
        if existing.request_hash != digest:
            raise AppError(
                status_code=409,
                code="idempotency_conflict",
                message="idempotency key was already used for another request",
            )
        return existing, False

    record = IdempotencyRecord(
        workspace_id=workspace_id,
        actor_id=actor_id,
        method=method,
        resource=resource,
        idempotency_key=key,
        request_hash=digest,
        status_code=0,
        response_json="{}",
    )
    try:
        async with db.begin_nested():
            db.add(record)
            await db.flush()
    except IntegrityError as exc:
        existing = (await db.execute(query)).scalar_one()
        if existing.request_hash != digest:
            raise AppError(
                status_code=409,
                code="idempotency_conflict",
                message="idempotency key was already used for another request",
            ) from exc
        return existing, False
    return record, True


def _replay_idempotency(record: IdempotencyRecord) -> JSONResponse:
    if record.status_code == 0:
        raise AppError(
            status_code=409,
            code="idempotency_in_progress",
            message="the original request is still in progress",
            retryable=True,
        )
    return _json_response(json.loads(record.response_json), record.status_code)


async def _find_submission(
    db: AsyncSession,
    conversation_id: str,
    client_message_id: str,
) -> tuple[Message, Run] | None:
    message = (
        await db.execute(
            select(Message).where(
                Message.conversation_id == conversation_id,
                Message.client_message_id == client_message_id,
            )
        )
    ).scalar_one_or_none()
    if message is None:
        return None
    run = (
        await db.execute(
            select(Run).where(
                Run.conversation_id == conversation_id,
                Run.client_message_id == client_message_id,
            )
        )
    ).scalar_one_or_none()
    if run is None:
        raise AppError(
            status_code=503,
            code="submission_incomplete",
            message="submission state is incomplete",
            retryable=True,
        )
    return message, run


async def _start_submission(
    db: AsyncSession,
    user: User,
    conversation_id: str,
    payload: MessageCreateIn,
) -> tuple[Conversation, Message, Run, bool]:
    source_conversation = await _resolve_conversation(
        db,
        user,
        conversation_id,
    )
    workspace = (
        await db.execute(
            select(Workspace).where(Workspace.id == source_conversation.workspace_id).with_for_update()
        )
    ).scalar_one_or_none()
    if workspace is None:
        raise AppError(status_code=404, code="resource_not_found", message="workspace not found")
    if workspace.service_mode != "open":
        raise AppError(
            status_code=409,
            code="service_paused",
            message=workspace.service_reason or "AI service is currently closed",
        )
    version = None
    if source_conversation.current_assistant_version_id is not None:
        version = (
            await db.execute(
                select(AssistantVersion)
                .where(
                    AssistantVersion.id == source_conversation.current_assistant_version_id,
                    AssistantVersion.workspace_id == workspace.id,
                )
                .with_for_update()
            )
        ).scalar_one_or_none()
    conversation = await _resolve_conversation(
        db,
        user,
        conversation_id,
        for_update=True,
    )
    if (
        conversation.workspace_id != workspace.id
        or conversation.current_assistant_version_id
        != source_conversation.current_assistant_version_id
    ):
        raise AppError(
            status_code=409,
            code="conversation_conflict",
            message="conversation configuration changed",
        )

    existing = await _find_submission(db, conversation.id, payload.client_message_id)
    if existing is not None:
        message, run = existing
        if message.content != payload.content:
            raise AppError(
                status_code=409,
                code="idempotency_conflict",
                message="client_message_id was already used with different content",
            )
        return conversation, message, run, True

    if conversation.revision != payload.expected_conversation_revision:
        raise AppError(
            status_code=409,
            code="conversation_conflict",
            message="conversation revision changed",
            details={"current_revision": conversation.revision},
        )

    active_run = (
        await db.execute(
            select(Run.id).where(
                Run.conversation_id == conversation.id,
                Run.status.in_(("created", "running", "reviewing")),
            )
        )
    ).scalar_one_or_none()
    if active_run is not None:
        raise AppError(
            status_code=409,
            code="conversation_conflict",
            message="conversation already has an active run",
        )

    last_seq = (
        await db.execute(
            select(Message.seq)
            .where(Message.conversation_id == conversation.id)
            .order_by(Message.seq.desc())
            .limit(1)
        )
    ).scalar_one_or_none() or 0
    turn_id = new_uuid()
    message = Message(
        conversation_id=conversation.id,
        turn_id=turn_id,
        role="user",
        content=payload.content,
        seq=last_seq + 1,
        client_message_id=payload.client_message_id,
    )
    if conversation.current_assistant_version_id is not None:
        if version is None or version.status != "active":
            raise AppError(
                status_code=409,
                code="assistant_version_unavailable",
                message="conversation assistant version is not active",
            )
    run = Run(
        conversation_id=conversation.id,
        turn_id=turn_id,
        client_message_id=payload.client_message_id,
        assistant_version_id=conversation.current_assistant_version_id,
        status="running",
        write_epoch=conversation.run_epoch,
        visible_content_version=0,
    )
    db.add_all([message, run])
    conversation.turn_count += 1
    conversation.revision += 1
    conversation.last_activity_at = utc_now()
    await db.flush()
    return conversation, message, run, False


@router.get("")
async def list_conversations(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    limit: int = Query(default=20, ge=1, le=100),
    cursor: str | None = None,
    q: str | None = Query(default=None, max_length=128),
    status_filter: str | None = Query(default=None, alias="status", max_length=32),
):
    statement = select(Conversation).where(
        Conversation.workspace_id == user.workspace_id,
        Conversation.owner_id == user.id,
        Conversation.deleted_at.is_(None),
        Conversation.turn_count > 0,
    )
    if q:
        statement = statement.where(Conversation.subject.ilike(f"%{q}%"))
    if status_filter:
        statement = statement.where(Conversation.status == status_filter)
    if cursor:
        try:
            decoded = decode_cursor(cursor, settings.secret_key)
            if (
                decoded.get("actor_id") != user.id
                or decoded.get("q") != q
                or decoded.get("status") != status_filter
            ):
                raise ValueError("cursor scope mismatch")
            cursor_time = datetime.fromisoformat(str(decoded["last_activity_at"]))
            cursor_id = str(decoded["id"])
        except (KeyError, TypeError, ValueError):
            raise AppError(
                status_code=422,
                code="validation_error",
                message="invalid cursor",
            ) from None
        statement = statement.where(
            or_(
                Conversation.last_activity_at < cursor_time,
                and_(
                    Conversation.last_activity_at == cursor_time,
                    Conversation.id < cursor_id,
                ),
            )
        )
    statement = statement.order_by(
        Conversation.last_activity_at.desc(),
        Conversation.id.desc(),
    ).limit(limit + 1)
    rows = list((await db.execute(statement)).scalars().all())
    has_more = len(rows) > limit
    visible_rows = rows[:limit]
    next_cursor = None
    if has_more and visible_rows:
        last = visible_rows[-1]
        if last.last_activity_at is None:
            raise AppError(
                status_code=503,
                code="conversation_state_invalid",
                message="conversation activity timestamp is missing",
                retryable=True,
            )
        next_cursor = encode_cursor(
            {
                "actor_id": user.id,
                "q": q,
                "status": status_filter,
                "last_activity_at": ensure_utc(last.last_activity_at).isoformat(),
                "id": last.id,
            },
            settings.secret_key,
        )
    return _env(
        {
            "items": [_conversation_payload(item) for item in visible_rows],
            "next_cursor": next_cursor,
            "has_more": has_more,
        }
    )


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_conversation(
    payload: ConversationCreateIn,
    response: Response,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _csrf: None = Depends(require_csrf_for_session),
    idempotency_key: str = Header(alias="Idempotency-Key", min_length=1, max_length=128),
):
    assistant_version_id = None
    if payload.assistant_id is not None:
        assistant = (
            await db.execute(
                select(Assistant).where(
                    Assistant.id == payload.assistant_id,
                    Assistant.workspace_id == user.workspace_id,
                )
            )
        ).scalar_one_or_none()
        if assistant is None or assistant.default_version_id is None:
            raise AppError(
                status_code=409,
                code="assistant_unavailable",
                message="assistant has no active default version",
            )
        version = await db.get(AssistantVersion, assistant.default_version_id)
        if version is None or version.workspace_id != user.workspace_id or version.status != "active":
            raise AppError(
                status_code=409,
                code="assistant_unavailable",
                message="assistant default version is not active",
            )
        assistant_version_id = version.id
    digest = request_digest(payload.model_dump())
    record, claimed = await _claim_idempotency(
        db,
        workspace_id=user.workspace_id,
        actor_id=user.id,
        method="POST",
        resource="/conversations",
        key=idempotency_key,
        digest=digest,
    )
    if not claimed:
        stored = json.loads(record.response_json)
        conversation_id = stored.get("id")
        if not isinstance(conversation_id, str):
            return _replay_idempotency(record)
        conversation = await _resolve_conversation(db, user, conversation_id)
        return _json_response(_conversation_payload(conversation), record.status_code)

    conversation = Conversation(
        workspace_id=user.workspace_id,
        owner_id=user.id,
        assistant_id=payload.assistant_id,
        current_assistant_version_id=assistant_version_id,
        subject=payload.subject or "new conversation",
    )
    db.add(conversation)
    await db.flush()
    result = _conversation_payload(conversation)
    record.status_code = status.HTTP_201_CREATED
    record.response_json = json.dumps(result)
    response.status_code = status.HTTP_201_CREATED
    return _env(result)


@router.get("/{conversation_id}")
async def get_conversation(
    conversation_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    conversation = await _resolve_conversation(db, user, conversation_id)
    return _env(_conversation_payload(conversation))


@router.patch("/{conversation_id}")
async def update_conversation(
    conversation_id: str,
    payload: ConversationPatchIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _csrf: None = Depends(require_csrf_for_session),
):
    conversation = await _resolve_conversation(
        db,
        user,
        conversation_id,
        for_update=True,
    )
    if conversation.revision != payload.expected_revision:
        raise AppError(
            status_code=409,
            code="conversation_conflict",
            message="conversation revision changed",
            details={"current_revision": conversation.revision},
        )
    conversation.subject = payload.subject.strip()
    conversation.revision += 1
    await db.flush()
    return _env(_conversation_payload(conversation))


@router.get("/{conversation_id}/messages")
async def list_messages(
    conversation_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    limit: int = Query(default=50, ge=1, le=100),
    cursor: int | None = Query(default=None, ge=0),
):
    await _resolve_conversation(db, user, conversation_id)
    statement = select(Message).where(
        Message.conversation_id == conversation_id,
        Message.visible.is_(True),
    )
    if cursor is not None:
        statement = statement.where(Message.seq > cursor)
    rows = list(
        (
            await db.execute(statement.order_by(Message.seq.asc()).limit(limit + 1))
        ).scalars().all()
    )
    has_more = len(rows) > limit
    visible_rows = rows[:limit]
    return _env(
        {
            "items": [
                {
                    "id": row.id,
                    "turn_id": row.turn_id,
                    "role": row.role,
                    "content": row.content,
                    "seq": row.seq,
                    "client_message_id": row.client_message_id,
                    "created_at": ensure_utc(row.created_at).isoformat(),
                }
                for row in visible_rows
            ],
            "next_cursor": visible_rows[-1].seq if has_more and visible_rows else None,
            "has_more": has_more,
        }
    )


@router.get("/{conversation_id}/submissions/{client_message_id}")
async def get_submission(
    conversation_id: str,
    client_message_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    conversation = await _resolve_conversation(db, user, conversation_id)
    result = await _find_submission(db, conversation.id, client_message_id)
    if result is None:
        raise AppError(status_code=404, code="resource_not_found", message="submission not found")
    _, run = result
    return _env(_run_snapshot(conversation, run, replayed=False))


@router.post("/{conversation_id}/messages")
async def send_message(
    conversation_id: str,
    payload: MessageCreateIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _csrf: None = Depends(require_csrf_for_session),
):
    conversation, _, run, replayed = await _start_submission(
        db,
        user,
        conversation_id,
        payload,
    )
    if replayed:
        return _env(_run_snapshot(conversation, run, replayed=True))

    if run.assistant_version_id is not None:
        await db.commit()
        try:
            async with AsyncSessionFactory() as dispatch_session:
                dispatch = await reserve_generation(
                    dispatch_session,
                    run_id=run.id,
                    user_content=payload.content,
                )
                await dispatch_session.commit()
            completion = await complete(
                base_url=dispatch.base_url,
                secret=dispatch.secret,
                model_id=dispatch.model_id,
                system_prompt=dispatch.system_prompt,
                user_content=payload.content,
                max_output_tokens=dispatch.max_output_tokens,
            )
            await settle_generation(dispatch.attempt_id, completion.usage)
            return _env(
                await _complete_provider_run(
                    run_id=run.id,
                    expected_epoch=run.write_epoch,
                    answer=completion.text,
                    published_seq=1,
                )
            )
        except AppError as exc:
            await _fail_provider_run(run_id=run.id, error_code=exc.code)
            raise
        except ProviderError as exc:
            if "dispatch" in locals():
                await mark_generation_failed(
                    dispatch.attempt_id,
                    error_code=exc.code,
                    outcome_unknown=exc.outcome_unknown,
                )
            snapshot = await _fail_provider_run(run_id=run.id, error_code=exc.code)
            raise AppError(
                status_code=502,
                code=exc.code,
                message="provider generation failed",
                retryable=exc.retryable,
                details={"run_id": run.id, "status": snapshot["status"] if snapshot else "unknown"},
            ) from None

    answer = f"Mock response: {payload.content}"
    last_seq = (
        await db.execute(
            select(Message.seq)
            .where(Message.conversation_id == conversation.id)
            .order_by(Message.seq.desc())
            .limit(1)
        )
    ).scalar_one()
    answer_message = Message(
        conversation_id=conversation.id,
        turn_id=run.turn_id,
        role="assistant",
        content=answer,
        seq=last_seq + 1,
    )
    db.add(answer_message)
    await db.flush()
    run.status = "completed"
    run.answer_text = answer
    run.visible_content_version = 1
    run.published_seq = 1
    conversation.active_answer_id = answer_message.id
    conversation.valid_reply_count += 1
    conversation.revision += 1
    conversation.last_activity_at = utc_now()
    await db.flush()
    return _env(_run_snapshot(conversation, run, replayed=False))


async def _cancel_interrupted_stream(run_id: str) -> None:
    async with AsyncSessionFactory() as session:
        run = await session.get(Run, run_id)
        if run is not None and run.status == "running":
            run.status = "cancelled"
            run.error_code = "client_disconnected"
            await session.commit()


async def _stream_publication_allowed(
    run_id: str,
    *,
    expected_epoch: int,
    expected_status: str,
) -> bool:
    async with AsyncSessionFactory() as session:
        row = (
            await session.execute(
                select(Run, Conversation, Workspace, AssistantVersion)
                .join(Conversation, Conversation.id == Run.conversation_id)
                .join(Workspace, Workspace.id == Conversation.workspace_id)
                .outerjoin(AssistantVersion, AssistantVersion.id == Run.assistant_version_id)
                .where(Run.id == run_id)
            )
        ).one_or_none()
    if row is None:
        return False
    run, conversation, workspace, assistant_version = row
    return (
        run.status == expected_status
        and run.write_epoch == expected_epoch
        and conversation.run_epoch == expected_epoch
        and conversation.deleted_at is None
        and workspace.service_mode == "open"
        and (run.assistant_version_id is None or assistant_version is not None)
        and (assistant_version is None or assistant_version.status == "active")
    )


async def _persist_provider_chunk(
    *,
    run_id: str,
    conversation_id: str,
    workspace_id: str,
    expected_epoch: int,
    chunk: str,
    stream_seq: int,
) -> int | None:
    async with AsyncSessionFactory() as session:
        locked_run = (
            await session.execute(select(Run).where(Run.id == run_id).with_for_update())
        ).scalar_one_or_none()
        conversation = (
            await session.execute(
                select(Conversation).where(Conversation.id == conversation_id).with_for_update()
            )
        ).scalar_one_or_none()
        workspace = await session.get(Workspace, workspace_id)
        version = (
            await session.get(AssistantVersion, locked_run.assistant_version_id)
            if locked_run is not None and locked_run.assistant_version_id
            else None
        )
        if (
            locked_run is None
            or conversation is None
            or workspace is None
            or locked_run.status != "running"
            or locked_run.write_epoch != expected_epoch
            or conversation.run_epoch != expected_epoch
            or conversation.deleted_at is not None
            or workspace.service_mode != "open"
            or (locked_run.assistant_version_id is not None and (version is None or version.status != "active"))
        ):
            await session.rollback()
            return None
        locked_run.answer_text = (locked_run.answer_text or "") + chunk
        locked_run.visible_content_version += 1
        locked_run.published_seq = stream_seq
        await session.commit()
        return locked_run.visible_content_version


async def _complete_provider_run(
    *,
    run_id: str,
    expected_epoch: int,
    answer: str | None,
    published_seq: int,
) -> dict[str, object]:
    async with AsyncSessionFactory() as session:
        locked_run = (
            await session.execute(select(Run).where(Run.id == run_id).with_for_update())
        ).scalar_one_or_none()
        if locked_run is None:
            raise AppError(status_code=404, code="resource_not_found", message="run not found")
        conversation = (
            await session.execute(
                select(Conversation)
                .where(Conversation.id == locked_run.conversation_id)
                .with_for_update()
            )
        ).scalar_one()
        workspace = await session.get(Workspace, conversation.workspace_id)
        version = (
            await session.get(AssistantVersion, locked_run.assistant_version_id)
            if locked_run.assistant_version_id
            else None
        )
        allowed = (
            locked_run.status == "running"
            and locked_run.write_epoch == expected_epoch
            and conversation.run_epoch == expected_epoch
            and conversation.deleted_at is None
            and workspace is not None
            and workspace.service_mode == "open"
            and (locked_run.assistant_version_id is None or (version is not None and version.status == "active"))
        )
        if not allowed:
            if locked_run.status == "running":
                locked_run.status = "cancelled"
                locked_run.error_code = "publication_revoked"
                conversation.revision += 1
            await session.commit()
            return _run_snapshot(conversation, locked_run, replayed=False)
        if answer is not None:
            locked_run.answer_text = answer
            locked_run.visible_content_version = max(locked_run.visible_content_version, 1)
        complete_text = locked_run.answer_text or ""
        if not complete_text:
            locked_run.status = "failed"
            locked_run.error_code = "provider_empty_response"
            conversation.revision += 1
            await session.commit()
            return _run_snapshot(conversation, locked_run, replayed=False)
        last_seq = (
            await session.execute(
                select(Message.seq)
                .where(Message.conversation_id == conversation.id)
                .order_by(Message.seq.desc())
                .limit(1)
            )
        ).scalar_one()
        answer_message = Message(
            conversation_id=conversation.id,
            turn_id=locked_run.turn_id,
            role="assistant",
            content=complete_text,
            seq=last_seq + 1,
        )
        session.add(answer_message)
        await session.flush()
        locked_run.status = "completed"
        locked_run.visible_content_version += 1
        locked_run.published_seq = published_seq
        conversation.active_answer_id = answer_message.id
        conversation.valid_reply_count += 1
        conversation.revision += 1
        conversation.last_activity_at = utc_now()
        await session.commit()
        return _run_snapshot(conversation, locked_run, replayed=False)


async def _fail_provider_run(
    *,
    run_id: str,
    error_code: str,
) -> dict[str, object] | None:
    async with AsyncSessionFactory() as session:
        locked_run = (
            await session.execute(select(Run).where(Run.id == run_id).with_for_update())
        ).scalar_one_or_none()
        if locked_run is None:
            return None
        conversation = (
            await session.execute(
                select(Conversation)
                .where(Conversation.id == locked_run.conversation_id)
                .with_for_update()
            )
        ).scalar_one()
        if locked_run.status == "running":
            locked_run.status = "failed"
            locked_run.error_code = error_code
            conversation.revision += 1
        await session.commit()
        return _run_snapshot(conversation, locked_run, replayed=False)


@router.post("/{conversation_id}/messages:stream")
@router.post("/{conversation_id}/messages/stream", include_in_schema=False)
async def stream_message(
    conversation_id: str,
    payload: MessageCreateIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _csrf: None = Depends(require_csrf_for_session),
):
    conversation, _, run, replayed = await _start_submission(
        db,
        user,
        conversation_id,
        payload,
    )
    if replayed:
        return _json_response(_run_snapshot(conversation, run, replayed=True))

    if run.assistant_version_id is not None:
        await db.commit()
        try:
            async with AsyncSessionFactory() as dispatch_session:
                dispatch = await reserve_generation(
                    dispatch_session,
                    run_id=run.id,
                    user_content=payload.content,
                )
                await dispatch_session.commit()
        except AppError as exc:
            await _fail_provider_run(run_id=run.id, error_code=exc.code)
            raise
        initial_revision = conversation.revision
        request_id = get_request_id()

        async def provider_events():
            stream_seq = 1
            usage = ProviderUsage(input_tokens=None, output_tokens=None, provider_request_id=None)
            created_event = {
                "conversation_id": conversation.id,
                "turn_id": run.turn_id,
                "run_id": run.id,
                "write_epoch": run.write_epoch,
                "stream_seq": stream_seq,
                "visible_content_version": 0,
                "conversation_revision": initial_revision,
                "status": "running",
            }
            try:
                if not await _stream_publication_allowed(
                    run.id,
                    expected_epoch=run.write_epoch,
                    expected_status="running",
                ):
                    await mark_generation_failed(
                        dispatch.attempt_id,
                        error_code="publication_revoked",
                        outcome_unknown=False,
                    )
                    await _fail_provider_run(run_id=run.id, error_code="publication_revoked")
                    return
                yield f"event: run.created\ndata: {json.dumps(created_event)}\n\n"
                async for event in stream_completion(
                    base_url=dispatch.base_url,
                    secret=dispatch.secret,
                    model_id=dispatch.model_id,
                    system_prompt=dispatch.system_prompt,
                    user_content=payload.content,
                    max_output_tokens=dispatch.max_output_tokens,
                ):
                    usage = event.usage or usage
                    if event.text is None:
                        continue
                    stream_seq += 1
                    visible_content_version = await _persist_provider_chunk(
                        run_id=run.id,
                        conversation_id=conversation.id,
                        workspace_id=conversation.workspace_id,
                        expected_epoch=run.write_epoch,
                        chunk=event.text,
                        stream_seq=stream_seq,
                    )
                    if visible_content_version is None:
                        await mark_generation_failed(
                            dispatch.attempt_id,
                            error_code="publication_revoked",
                            outcome_unknown=True,
                        )
                        await _fail_provider_run(run_id=run.id, error_code="publication_revoked")
                        return
                    delta_event = {
                        **created_event,
                        "stream_seq": stream_seq,
                        "visible_content_version": visible_content_version,
                        "text": event.text,
                    }
                    yield f"event: answer.delta\ndata: {json.dumps(delta_event)}\n\n"
                await settle_generation(dispatch.attempt_id, usage)
                stream_seq += 1
                snapshot = await _complete_provider_run(
                    run_id=run.id,
                    expected_epoch=run.write_epoch,
                    answer=None,
                    published_seq=stream_seq,
                )
                if snapshot["status"] != "completed":
                    yield (
                        "event: run.failed\ndata: "
                        + json.dumps({**created_event, "status": snapshot["status"], "error": snapshot["error"]})
                        + "\n\n"
                    )
                    return
                completed = {
                    **created_event,
                    "stream_seq": stream_seq,
                    "visible_content_version": snapshot["visible_content_version"],
                    "conversation_revision": snapshot["conversation_revision"],
                    "status": "completed",
                    "active_answer_id": snapshot["active_answer_id"],
                    "is_complete": True,
                }
                yield f"event: run.completed\ndata: {json.dumps(completed)}\n\n"
            except ProviderError as exc:
                await mark_generation_failed(
                    dispatch.attempt_id,
                    error_code=exc.code,
                    outcome_unknown=exc.outcome_unknown,
                )
                snapshot = await _fail_provider_run(run_id=run.id, error_code=exc.code)
                failed = {
                    **created_event,
                    "status": "failed",
                    "error": exc.code,
                    "retryable": exc.retryable,
                    "conversation_revision": snapshot["conversation_revision"] if snapshot else initial_revision,
                }
                yield f"event: run.failed\ndata: {json.dumps(failed)}\n\n"
            except (asyncio.CancelledError, GeneratorExit):
                await mark_generation_failed(
                    dispatch.attempt_id,
                    error_code="client_disconnected",
                    outcome_unknown=True,
                )
                await _cancel_interrupted_stream(run.id)
                raise

        return StreamingResponse(
            provider_events(),
            media_type="text/event-stream",
            headers={
                "X-Request-ID": request_id,
                "Cache-Control": "no-store",
                "X-Accel-Buffering": "no",
            },
        )

    await db.commit()
    initial_revision = conversation.revision
    request_id = get_request_id()

    async def events():
        stream_seq = 1
        created_event = {
            "conversation_id": conversation.id,
            "turn_id": run.turn_id,
            "run_id": run.id,
            "write_epoch": run.write_epoch,
            "stream_seq": stream_seq,
            "visible_content_version": 0,
            "conversation_revision": initial_revision,
            "status": "running",
        }
        try:
            if not await _stream_publication_allowed(
                run.id,
                expected_epoch=run.write_epoch,
                expected_status="running",
            ):
                return
            yield f"event: run.created\ndata: {json.dumps(created_event)}\n\n"
            answer = f"Mock response: {payload.content}"
            for chunk in [answer[index : index + 16] for index in range(0, len(answer), 16)]:
                await asyncio.sleep(0.01)
                stream_seq += 1
                async with AsyncSessionFactory() as session:
                    locked_run = (
                        await session.execute(
                            select(Run).where(Run.id == run.id).with_for_update()
                        )
                    ).scalar_one_or_none()
                    locked_conversation = (
                        await session.execute(
                            select(Conversation)
                            .where(Conversation.id == conversation.id)
                            .with_for_update()
                        )
                    ).scalar_one_or_none()
                    workspace = (
                        await session.execute(
                            select(Workspace).where(Workspace.id == conversation.workspace_id)
                        )
                    ).scalar_one_or_none()
                    if (
                        locked_run is None
                        or locked_conversation is None
                        or workspace is None
                        or locked_run.status != "running"
                        or locked_run.write_epoch != run.write_epoch
                        or locked_conversation.run_epoch != run.write_epoch
                        or locked_conversation.deleted_at is not None
                        or workspace.service_mode != "open"
                    ):
                        await session.rollback()
                        return
                    locked_run.answer_text = (locked_run.answer_text or "") + chunk
                    locked_run.visible_content_version += 1
                    locked_run.published_seq = stream_seq
                    await session.commit()
                    visible_content_version = locked_run.visible_content_version

                if not await _stream_publication_allowed(
                    run.id,
                    expected_epoch=run.write_epoch,
                    expected_status="running",
                ):
                    return
                delta_event = {
                    **created_event,
                    "stream_seq": stream_seq,
                    "visible_content_version": visible_content_version,
                    "text": chunk,
                }
                yield f"event: answer.delta\ndata: {json.dumps(delta_event)}\n\n"

            async with AsyncSessionFactory() as session:
                locked_run = (
                    await session.execute(
                        select(Run).where(Run.id == run.id).with_for_update()
                    )
                ).scalar_one()
                locked_conversation = (
                    await session.execute(
                        select(Conversation)
                        .where(Conversation.id == conversation.id)
                        .with_for_update()
                    )
                ).scalar_one()
                workspace = await session.get(Workspace, locked_conversation.workspace_id)
                if (
                    locked_run.status != "running"
                    or workspace is None
                    or locked_run.write_epoch != run.write_epoch
                    or locked_conversation.run_epoch != run.write_epoch
                    or locked_conversation.deleted_at is not None
                    or workspace.service_mode != "open"
                ):
                    await session.rollback()
                    return

                last_seq = (
                    await session.execute(
                        select(Message.seq)
                        .where(Message.conversation_id == conversation.id)
                        .order_by(Message.seq.desc())
                        .limit(1)
                    )
                ).scalar_one()
                answer_message = Message(
                    conversation_id=conversation.id,
                    turn_id=run.turn_id,
                    role="assistant",
                    content=locked_run.answer_text or "",
                    seq=last_seq + 1,
                )
                session.add(answer_message)
                await session.flush()
                locked_run.status = "completed"
                locked_run.visible_content_version += 1
                locked_run.published_seq = stream_seq + 1
                locked_conversation.active_answer_id = answer_message.id
                locked_conversation.valid_reply_count += 1
                locked_conversation.revision += 1
                locked_conversation.last_activity_at = utc_now()
                await session.commit()
                final_revision = locked_conversation.revision

            stream_seq += 1
            if not await _stream_publication_allowed(
                run.id,
                expected_epoch=run.write_epoch,
                expected_status="completed",
            ):
                return
            completed = {
                **created_event,
                "stream_seq": stream_seq,
                "visible_content_version": locked_run.visible_content_version,
                "conversation_revision": final_revision,
                "status": "completed",
                "active_answer_id": answer_message.id,
                "is_complete": True,
            }
            yield f"event: run.completed\ndata: {json.dumps(completed)}\n\n"
        except (asyncio.CancelledError, GeneratorExit):
            await _cancel_interrupted_stream(run.id)
            raise

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={
            "X-Request-ID": request_id,
            "Cache-Control": "no-store",
            "X-Accel-Buffering": "no",
        },
    )


async def _append_deletion_journal(
    *,
    workspace_id: str,
    actor_id: str,
    operation_id: str,
    conversation_id: str,
    digest: str,
) -> int:
    try:
        async with JournalSessionFactory() as journal:
            existing = (
                await journal.execute(
                    select(DeletionJournal).where(
                        DeletionJournal.workspace_id == workspace_id,
                        DeletionJournal.operation_id == operation_id,
                    )
                )
            ).scalar_one_or_none()
            if existing is not None:
                if existing.request_hash != digest:
                    raise AppError(
                        status_code=409,
                        code="idempotency_conflict",
                        message="deletion operation conflicts with prior request",
                    )
                return existing.seq

            dialect_name = journal.bind.dialect.name if journal.bind is not None else ""
            if dialect_name == "postgresql":
                await journal.execute(
                    postgresql_insert(JournalHead)
                    .values(workspace_id=workspace_id, head_seq=0, updated_at=utc_now())
                    .on_conflict_do_nothing(index_elements=["workspace_id"])
                )
            elif dialect_name == "sqlite":
                await journal.execute(
                    sqlite_insert(JournalHead)
                    .values(workspace_id=workspace_id, head_seq=0, updated_at=utc_now())
                    .on_conflict_do_nothing(index_elements=["workspace_id"])
                )
            head = (
                await journal.execute(
                    select(JournalHead)
                    .where(JournalHead.workspace_id == workspace_id)
                    .with_for_update()
                )
            ).scalar_one_or_none()
            if head is None:
                head = JournalHead(workspace_id=workspace_id, head_seq=0)
                journal.add(head)
                await journal.flush()
            head.head_seq += 1
            head.updated_at = utc_now()
            journal.add(
                DeletionJournal(
                    id=new_uuid(),
                    workspace_id=workspace_id,
                    seq=head.head_seq,
                    operation_id=operation_id,
                    resource_type="conversation",
                    resource_id=conversation_id,
                    request_hash=digest,
                    actor_id=actor_id,
                    instance_id=settings.instance_id,
                    payload_json=json.dumps(
                        {"resource_type": "conversation", "resource_id": conversation_id}
                    ),
                )
            )
            await journal.commit()
            return head.head_seq
    except AppError:
        raise
    except SQLAlchemyError as exc:
        raise AppError(
            status_code=503,
            code="deletion_journal_unavailable",
            message="deletion journal could not confirm the request",
            retryable=True,
        ) from exc


@router.delete("/{conversation_id}", status_code=status.HTTP_202_ACCEPTED)
async def delete_conversation(
    conversation_id: str,
    expected_conversation_revision: int = Query(ge=1),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _csrf: None = Depends(require_csrf_for_session),
    idempotency_key: str = Header(alias="Idempotency-Key", min_length=1, max_length=128),
):
    digest = request_digest(
        {
            "conversation_id": conversation_id,
            "expected_conversation_revision": expected_conversation_revision,
        }
    )
    record, claimed = await _claim_idempotency(
        db,
        workspace_id=user.workspace_id,
        actor_id=user.id,
        method="DELETE",
        resource=f"/conversations/{conversation_id}",
        key=idempotency_key,
        digest=digest,
    )
    operation_id = str(
        uuid5(
            NAMESPACE_URL,
            f"{user.workspace_id}:{user.id}:DELETE:{conversation_id}:{idempotency_key}",
        )
    )
    if claimed:
        conversation = await _resolve_conversation(
            db,
            user,
            conversation_id,
            for_update=True,
        )
        if conversation.revision != expected_conversation_revision:
            raise AppError(
                status_code=409,
                code="conversation_conflict",
                message="conversation revision changed",
                details={"current_revision": conversation.revision},
            )
        job = Job(
            workspace_id=user.workspace_id,
            actor_id=user.id,
            type="conversation_deletion",
            status="blocked",
            stage="intent_persisted",
            resource_type="conversation",
            resource_id=conversation_id,
            retryable=True,
        )
        db.add(job)
        await db.flush()
        db.add(
            DeletionIntent(
                workspace_id=user.workspace_id,
                actor_id=user.id,
                operation_id=operation_id,
                resource_type="conversation",
                resource_id=conversation_id,
                request_hash=digest,
                job_id=job.id,
            )
        )
        conversation.deleted_at = utc_now()
        conversation.status = "deleting"
        conversation.run_epoch += 1
        conversation.revision += 1
        await db.execute(
            update(Run)
            .where(
                Run.conversation_id == conversation.id,
                Run.status.in_(("created", "running", "reviewing")),
            )
            .values(status="cancelled", error_code="resource_deleted")
        )
        await db.commit()
    elif record.status_code != 0:
        return _replay_idempotency(record)
    else:
        intent = (
            await db.execute(
                select(DeletionIntent).where(
                    DeletionIntent.workspace_id == user.workspace_id,
                    DeletionIntent.operation_id == operation_id,
                )
            )
        ).scalar_one_or_none()
        if intent is None:
            return _replay_idempotency(record)

    await _append_deletion_journal(
        workspace_id=user.workspace_id,
        actor_id=user.id,
        operation_id=operation_id,
        conversation_id=conversation_id,
        digest=digest,
    )
    try:
        await recover_deletion_journal()
    except DeletionRecoveryError as exc:
        raise AppError(
            status_code=503,
            code="deletion_recovery_pending",
            message="deletion journal projection could not be completed",
            retryable=True,
        ) from exc
    intent = (
        await db.execute(
            select(DeletionIntent).where(
                DeletionIntent.workspace_id == user.workspace_id,
                DeletionIntent.operation_id == operation_id,
            )
        )
    ).scalar_one_or_none()
    if intent is None:
        raise AppError(
            status_code=503,
            code="deletion_recovery_pending",
            message="deletion journal projection is not available yet",
            retryable=True,
        )
    recovered_job = await db.get(Job, intent.job_id)
    receipt = (
        await db.execute(
            select(DeletionReceipt).where(DeletionReceipt.job_id == intent.job_id)
        )
    ).scalar_one_or_none()
    if recovered_job is None or receipt is None:
        raise AppError(
            status_code=503,
            code="deletion_recovery_pending",
            message="deletion cleanup registration is not available yet",
            retryable=True,
        )
    result = {
        "receipt_id": receipt.id,
        "job_id": recovered_job.id,
        "status": "accepted",
        "online_cleanup_status": receipt.online_cleanup_status,
        "backup_disposal_status": receipt.backup_disposal_status,
    }
    record.status_code = status.HTTP_202_ACCEPTED
    record.response_json = json.dumps(result)
    return _json_response(result, status.HTTP_202_ACCEPTED)


@runs_router.get("/{run_id}")
async def get_run(
    run_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    run = await db.get(Run, run_id)
    if run is None:
        raise AppError(status_code=404, code="resource_not_found", message="run not found")
    conversation = await _resolve_conversation(db, user, run.conversation_id)
    return _env(_run_snapshot(conversation, run, replayed=False))


@runs_router.post("/{run_id}/cancel")
async def cancel_run(
    run_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _csrf: None = Depends(require_csrf_for_session),
    idempotency_key: str = Header(alias="Idempotency-Key", min_length=1, max_length=128),
):
    run = (
        await db.execute(select(Run).where(Run.id == run_id).with_for_update())
    ).scalar_one_or_none()
    if run is None:
        raise AppError(status_code=404, code="resource_not_found", message="run not found")
    conversation = await _resolve_conversation(
        db,
        user,
        run.conversation_id,
        for_update=True,
    )
    digest = request_digest({"run_id": run_id})
    record, claimed = await _claim_idempotency(
        db,
        workspace_id=user.workspace_id,
        actor_id=user.id,
        method="POST",
        resource=f"/runs/{run_id}/cancel",
        key=idempotency_key,
        digest=digest,
    )
    if not claimed:
        return _json_response(_run_snapshot(conversation, run, replayed=True))
    if run.status not in {"completed", "failed", "cancelled"}:
        run.status = "cancelled"
        conversation.revision += 1
        await db.flush()
    result = _run_snapshot(conversation, run, replayed=False)
    record.status_code = 200
    record.response_json = json.dumps(result)
    return _env(result)
