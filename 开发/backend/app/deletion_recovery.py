from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from app.core.db import AsyncSessionFactory
from app.core.journal_db import JournalSessionFactory
from app.core.security import utc_now
from app.journal_models import DeletionJournal, JournalHead
from app.models import (
    Conversation,
    DeletionIntent,
    DeletionReceipt,
    Job,
    JournalProjection,
    Run,
)


class DeletionRecoveryError(RuntimeError):
    pass


@dataclass(frozen=True)
class JournalEntry:
    workspace_id: str
    seq: int
    operation_id: str
    resource_type: str
    resource_id: str
    request_hash: str
    actor_id: str


def _entry_from_row(row: DeletionJournal) -> JournalEntry:
    return JournalEntry(
        workspace_id=row.workspace_id,
        seq=row.seq,
        operation_id=row.operation_id,
        resource_type=row.resource_type,
        resource_id=row.resource_id,
        request_hash=row.request_hash,
        actor_id=row.actor_id,
    )


async def _ensure_projection(session, workspace_id: str) -> JournalProjection:
    dialect_name = session.bind.dialect.name if session.bind is not None else ""
    values = {"workspace_id": workspace_id, "applied_seq": 0, "updated_at": utc_now()}
    if dialect_name == "postgresql":
        await session.execute(
            postgresql_insert(JournalProjection)
            .values(**values)
            .on_conflict_do_nothing(index_elements=["workspace_id"])
        )
    elif dialect_name == "sqlite":
        await session.execute(
            sqlite_insert(JournalProjection)
            .values(**values)
            .on_conflict_do_nothing(index_elements=["workspace_id"])
        )
    else:
        projection = await session.get(JournalProjection, workspace_id)
        if projection is None:
            session.add(JournalProjection(**values))
            await session.flush()
    projection = (
        await session.execute(
            select(JournalProjection)
            .where(JournalProjection.workspace_id == workspace_id)
            .with_for_update()
        )
    ).scalar_one()
    return projection


async def _apply_entry(entry: JournalEntry) -> bool:
    async with AsyncSessionFactory() as session:
        projection = await _ensure_projection(session, entry.workspace_id)
        if entry.seq <= projection.applied_seq:
            await session.commit()
            return False
        if entry.seq != projection.applied_seq + 1:
            await session.rollback()
            return False

        intent = (
            await session.execute(
                select(DeletionIntent)
                .where(
                    DeletionIntent.workspace_id == entry.workspace_id,
                    DeletionIntent.operation_id == entry.operation_id,
                )
                .with_for_update()
            )
        ).scalar_one_or_none()
        if intent is not None and (
            intent.resource_type != entry.resource_type
            or intent.resource_id != entry.resource_id
            or intent.request_hash != entry.request_hash
            or intent.actor_id != entry.actor_id
        ):
            raise DeletionRecoveryError("deletion journal entry conflicts with persisted intent")

        job: Job | None
        if intent is None:
            job = Job(
                workspace_id=entry.workspace_id,
                actor_id=entry.actor_id,
                type="conversation_deletion",
                status="queued",
                stage="journal_recovered",
                resource_type=entry.resource_type,
                resource_id=entry.resource_id,
            )
            session.add(job)
            await session.flush()
            intent = DeletionIntent(
                workspace_id=entry.workspace_id,
                actor_id=entry.actor_id,
                operation_id=entry.operation_id,
                resource_type=entry.resource_type,
                resource_id=entry.resource_id,
                request_hash=entry.request_hash,
                job_id=job.id,
                journal_seq=entry.seq,
                status="journal_recovered",
            )
            session.add(intent)
        else:
            job = await session.get(Job, intent.job_id, with_for_update=True)
            if job is None:
                job = Job(
                    id=intent.job_id,
                    workspace_id=entry.workspace_id,
                    actor_id=entry.actor_id,
                    type="conversation_deletion",
                    status="queued",
                    stage="journal_recovered",
                    resource_type=entry.resource_type,
                    resource_id=entry.resource_id,
                )
                session.add(job)
            elif job.status == "blocked" and job.stage == "intent_persisted":
                job.status = "queued"
                job.stage = "journal_confirmed"
                job.error_code = None
                job.retryable = False
            intent.journal_seq = entry.seq
            intent.status = "journal_confirmed"

        if job is None:
            raise DeletionRecoveryError("deletion intent could not be associated with a cleanup job")

        conversation = await session.get(Conversation, entry.resource_id, with_for_update=True)
        if conversation is not None:
            if conversation.workspace_id != entry.workspace_id:
                raise DeletionRecoveryError("deletion journal workspace does not match conversation")
            if conversation.deleted_at is None:
                conversation.deleted_at = utc_now()
                conversation.status = "deleting"
                conversation.run_epoch += 1
            await session.execute(
                update(Run)
                .where(
                    Run.conversation_id == conversation.id,
                    Run.status.in_(("created", "running", "reviewing")),
                )
                .values(status="cancelled", error_code="resource_deleted")
            )

        receipt = (
            await session.execute(
                select(DeletionReceipt).where(
                    DeletionReceipt.workspace_id == entry.workspace_id,
                    DeletionReceipt.operation_id == entry.operation_id,
                )
            )
        ).scalar_one_or_none()
        if receipt is None:
            session.add(
                DeletionReceipt(
                    workspace_id=entry.workspace_id,
                    actor_id=entry.actor_id,
                    operation_id=entry.operation_id,
                    resource_type=entry.resource_type,
                    resource_id=entry.resource_id,
                    request_hash=entry.request_hash,
                    journal_seq=entry.seq,
                    job_id=intent.job_id,
                )
            )
        projection.applied_seq = entry.seq
        projection.updated_at = utc_now()
        await session.commit()
        return True


async def recover_deletion_journal() -> int:
    """Project every durable journal entry through the first missing sequence."""

    async with JournalSessionFactory() as journal_session:
        heads = list((await journal_session.execute(select(JournalHead))).scalars().all())

    applied_count = 0
    for head in heads:
        while True:
            async with AsyncSessionFactory() as business_session:
                projection = await business_session.get(JournalProjection, head.workspace_id)
                applied_seq = projection.applied_seq if projection is not None else 0
            if applied_seq >= head.head_seq:
                break

            async with JournalSessionFactory() as journal_session:
                row = (
                    await journal_session.execute(
                        select(DeletionJournal).where(
                            DeletionJournal.workspace_id == head.workspace_id,
                            DeletionJournal.seq == applied_seq + 1,
                        )
                    )
                ).scalar_one_or_none()
            if row is None:
                raise DeletionRecoveryError(
                    f"deletion journal has a gap at {head.workspace_id}:{applied_seq + 1}"
                )
            if await _apply_entry(_entry_from_row(row)):
                applied_count += 1
    return applied_count


async def deletion_recovery_is_current() -> bool:
    async with JournalSessionFactory() as journal_session:
        heads = list((await journal_session.execute(select(JournalHead))).scalars().all())
    async with AsyncSessionFactory() as business_session:
        for head in heads:
            projection = await business_session.get(JournalProjection, head.workspace_id)
            if projection is None or projection.applied_seq != head.head_seq:
                return False
    return True
