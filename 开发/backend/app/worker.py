from __future__ import annotations

import argparse
import asyncio
import json
from contextlib import suppress
from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import select, update

from app.core.config import settings
from app.core.db import AsyncSessionFactory
from app.core.errors import AppError
from app.core.journal_db import JournalSessionFactory
from app.core.security import decrypt_provider_secret, ensure_utc, utc_now
from app.deletion_recovery import recover_deletion_journal
from app.journal_models import DeletionJournal
from app.models import (
    Conversation,
    DeletionReceipt,
    Job,
    Message,
    ModelDeployment,
    ProviderConnection,
    ProviderConnectionTest,
    Run,
)
from app.services.billing import (
    mark_generation_failed,
    reserve_provider_connection_test,
    settle_generation,
)
from app.services.provider import ProviderError, complete, list_models

RETRY_DELAYS_SECONDS = (5, 15, 60, 300)


@dataclass(frozen=True)
class JobClaim:
    job_id: str
    claim_version: int
    claimed_by: str


async def _claim_job() -> JobClaim | None:
    now = utc_now()
    async with AsyncSessionFactory() as session:
        statement = (
            select(Job)
            .where(
                Job.available_at <= now,
                Job.attempt_count < settings.worker_max_attempts,
                (
                    (Job.status == "queued")
                    | (
                        (Job.status == "running")
                        & (Job.lease_expires_at.is_not(None))
                        & (Job.lease_expires_at < now)
                    )
                ),
            )
            .order_by(Job.created_at.asc(), Job.id.asc())
            .with_for_update(skip_locked=True)
            .limit(1)
        )
        job = (await session.execute(statement)).scalar_one_or_none()
        if job is None:
            return None
        job.status = "running"
        job.stage = "claimed"
        job.claimed_by = settings.instance_id
        job.claim_version += 1
        job.attempt_count += 1
        job.lease_expires_at = now + timedelta(seconds=settings.worker_lease_seconds)
        await session.commit()
        return JobClaim(
            job_id=job.id,
            claim_version=job.claim_version,
            claimed_by=settings.instance_id,
        )


async def _fail_exhausted_jobs() -> None:
    now = utc_now()
    async with AsyncSessionFactory() as session:
        await session.execute(
            update(Job)
            .where(
                Job.attempt_count >= settings.worker_max_attempts,
                (
                    (Job.status == "queued")
                    | (
                        (Job.status == "running")
                        & (Job.lease_expires_at.is_not(None))
                        & (Job.lease_expires_at < now)
                    )
                ),
            )
            .values(
                status="failed",
                stage="attempts_exhausted",
                error_code="worker_attempts_exhausted",
                retryable=False,
                claimed_by=None,
                lease_expires_at=None,
            )
        )
        await session.commit()


async def _journal_authorizes(receipt: DeletionReceipt) -> bool:
    async with JournalSessionFactory() as session:
        journal = (
            await session.execute(
                select(DeletionJournal).where(
                    DeletionJournal.workspace_id == receipt.workspace_id,
                    DeletionJournal.operation_id == receipt.operation_id,
                    DeletionJournal.seq == receipt.journal_seq,
                )
            )
        ).scalar_one_or_none()
        return journal is not None and journal.request_hash == receipt.request_hash


async def _claim_is_valid(job: Job, claim: JobClaim) -> bool:
    return (
        job.status == "running"
        and job.claimed_by == claim.claimed_by
        and job.claim_version == claim.claim_version
        and job.lease_expires_at is not None
        and ensure_utc(job.lease_expires_at) > utc_now()
    )


async def _renew_lease(claim: JobClaim) -> bool:
    now = utc_now()
    async with AsyncSessionFactory() as session:
        result = await session.execute(
            update(Job)
            .where(
                Job.id == claim.job_id,
                Job.status == "running",
                Job.claimed_by == claim.claimed_by,
                Job.claim_version == claim.claim_version,
                Job.lease_expires_at.is_not(None),
                Job.lease_expires_at > now,
            )
            .values(lease_expires_at=now + timedelta(seconds=settings.worker_lease_seconds))
        )
        await session.commit()
        return bool(getattr(result, "rowcount", 0) == 1)


async def _heartbeat(claim: JobClaim, stop: asyncio.Event) -> None:
    while not stop.is_set():
        try:
            await asyncio.wait_for(stop.wait(), timeout=settings.worker_heartbeat_seconds)
            return
        except TimeoutError:
            if not await _renew_lease(claim):
                return


async def _process_conversation_deletion(claim: JobClaim) -> None:
    async with AsyncSessionFactory() as session:
        job = await session.get(Job, claim.job_id)
        if job is None:
            return
        receipt = (
            await session.execute(
                select(DeletionReceipt).where(DeletionReceipt.job_id == job.id)
            )
        ).scalar_one_or_none()
        if receipt is None or not await _journal_authorizes(receipt):
            locked_job = (
                await session.execute(select(Job).where(Job.id == claim.job_id).with_for_update())
            ).scalar_one_or_none()
            if locked_job is None or not await _claim_is_valid(locked_job, claim):
                await session.rollback()
                return
            locked_job.status = "blocked"
            locked_job.stage = "journal_verification_failed"
            locked_job.error_code = "deletion_journal_unverified"
            locked_job.retryable = True
            locked_job.claimed_by = None
            locked_job.lease_expires_at = None
            await session.commit()
            return

        locked_job = (
            await session.execute(select(Job).where(Job.id == claim.job_id).with_for_update())
        ).scalar_one()
        if not await _claim_is_valid(locked_job, claim):
            return
        await session.execute(
            update(Message)
            .where(Message.conversation_id == receipt.resource_id)
            .values(content="", visible=False)
        )
        await session.execute(
            update(Run)
            .where(Run.conversation_id == receipt.resource_id)
            .values(answer_text=None)
        )
        await session.execute(
            update(Run)
            .where(
                Run.conversation_id == receipt.resource_id,
                Run.status.in_(("created", "running", "reviewing")),
            )
            .values(status="cancelled", error_code="resource_deleted")
        )
        conversation = await session.get(Conversation, receipt.resource_id)
        if conversation is not None:
            conversation.subject = "deleted conversation"
            conversation.status = "purged"
            conversation.active_answer_id = None
        receipt.online_cleanup_status = "completed"
        locked_job.status = "completed"
        locked_job.stage = "online_cleanup_completed"
        locked_job.error_code = None
        locked_job.retryable = False
        locked_job.claimed_by = None
        locked_job.lease_expires_at = None
        await session.commit()


async def _process_provider_connection_test(claim: JobClaim) -> None:
    async with AsyncSessionFactory() as session:
        test = (
            await session.execute(
                select(ProviderConnectionTest).where(ProviderConnectionTest.job_id == claim.job_id)
            )
        ).scalar_one_or_none()
        if test is None:
            await _fail_unsupported_claim(claim)
            return
        connection = await session.get(ProviderConnection, test.provider_connection_id)
        if (
            connection is None
            or connection.revision != test.expected_revision
            or not connection.secret_ciphertext
        ):
            error_code = "provider_connection_changed"
            base_url = None
            secret = None
        else:
            try:
                secret = decrypt_provider_secret(connection.secret_ciphertext)
            except ValueError:
                secret = None
                error_code = "provider_secret_unavailable"
                base_url = None
            else:
                base_url = connection.base_url
                error_code = None
    models: list[str] = []
    dispatch = None
    if error_code is None and base_url is not None and secret is not None:
        try:
            models = await list_models(base_url=base_url, secret=secret)
        except ProviderError as exc:
            error_code = exc.code
    if error_code is None:
        try:
            async with AsyncSessionFactory() as session:
                dispatch = await reserve_provider_connection_test(session, job_id=claim.job_id)
                await session.commit()
            completion = await complete(
                base_url=dispatch.base_url,
                secret=dispatch.secret,
                model_id=dispatch.model_id,
                system_prompt=dispatch.system_prompt,
                user_content="connection verification",
                max_output_tokens=dispatch.max_output_tokens,
            )
            await settle_generation(dispatch.attempt_id, completion.usage)
        except AppError as exc:
            error_code = exc.code
        except ProviderError as exc:
            if dispatch is not None:
                await mark_generation_failed(
                    dispatch.attempt_id,
                    error_code=exc.code,
                    outcome_unknown=exc.outcome_unknown,
                )
            error_code = exc.code

    async with AsyncSessionFactory() as session:
        job = (
            await session.execute(select(Job).where(Job.id == claim.job_id).with_for_update())
        ).scalar_one_or_none()
        test = (
            await session.execute(
                select(ProviderConnectionTest)
                .where(ProviderConnectionTest.job_id == claim.job_id)
                .with_for_update()
            )
        ).scalar_one_or_none()
        if job is None or test is None or not await _claim_is_valid(job, claim):
            await session.rollback()
            return
        connection = await session.get(ProviderConnection, test.provider_connection_id)
        if connection is None or connection.revision != test.expected_revision:
            error_code = "provider_connection_changed"
        configured_models = []
        if error_code is None:
            configured_models = list(
                (
                    await session.execute(
                        select(ModelDeployment.model_id).where(
                            ModelDeployment.provider_connection_id == test.provider_connection_id,
                            ModelDeployment.revision == test.expected_revision,
                            ModelDeployment.status == "active",
                        )
                    )
                ).scalars().all()
            )
            if not configured_models or not set(configured_models).issubset(set(models)):
                error_code = "provider_model_unavailable"
        test.completed_at = utc_now()
        test.result_json = json.dumps({"models": models[:100], "error_code": error_code})
        if error_code is None and connection is not None:
            test.status = "passed"
            connection.status = "ready"
            connection.last_tested_at = test.completed_at
            job.status = "completed"
            job.stage = "provider_test_passed"
            job.error_code = None
            job.retryable = False
        else:
            test.status = "failed"
            if connection is not None and connection.revision == test.expected_revision:
                connection.status = "failed"
                connection.last_tested_at = test.completed_at
            job.status = "failed"
            job.stage = "provider_test_failed"
            job.error_code = error_code
            job.retryable = False
        job.claimed_by = None
        job.lease_expires_at = None
        await session.commit()


async def _retry_or_fail_claim(claim: JobClaim, error_code: str) -> None:
    async with AsyncSessionFactory() as session:
        job = (
            await session.execute(select(Job).where(Job.id == claim.job_id).with_for_update())
        ).scalar_one_or_none()
        if job is None or not await _claim_is_valid(job, claim):
            await session.rollback()
            return
        if job.attempt_count >= settings.worker_max_attempts:
            job.status = "failed"
            job.stage = "attempts_exhausted"
            job.error_code = error_code
            job.retryable = False
            job.claimed_by = None
            job.lease_expires_at = None
        else:
            delay_index = min(job.attempt_count - 1, len(RETRY_DELAYS_SECONDS) - 1)
            job.status = "queued"
            job.stage = "retry_scheduled"
            job.error_code = error_code
            job.retryable = True
            job.available_at = utc_now() + timedelta(seconds=RETRY_DELAYS_SECONDS[delay_index])
            job.claimed_by = None
            job.lease_expires_at = None
        await session.commit()


async def _fail_unsupported_claim(claim: JobClaim) -> None:
    async with AsyncSessionFactory() as session:
        job = (
            await session.execute(select(Job).where(Job.id == claim.job_id).with_for_update())
        ).scalar_one_or_none()
        if job is None or not await _claim_is_valid(job, claim):
            await session.rollback()
            return
        job.status = "failed"
        job.stage = "unsupported_job_type"
        job.error_code = "unsupported_job_type"
        job.retryable = False
        job.claimed_by = None
        job.lease_expires_at = None
        await session.commit()


async def process_one_job() -> bool:
    await recover_deletion_journal()
    await _fail_exhausted_jobs()
    claim = await _claim_job()
    if claim is None:
        return False
    stop_heartbeat = asyncio.Event()
    heartbeat_task = asyncio.create_task(_heartbeat(claim, stop_heartbeat))
    try:
        async with AsyncSessionFactory() as session:
            job = await session.get(Job, claim.job_id)
            job_type = job.type if job else None
        if job_type == "conversation_deletion":
            await _process_conversation_deletion(claim)
        elif job_type == "provider_connection_test":
            await _process_provider_connection_test(claim)
        else:
            await _fail_unsupported_claim(claim)
    except Exception:
        await _retry_or_fail_claim(claim, "worker_execution_failed")
        raise
    finally:
        stop_heartbeat.set()
        heartbeat_task.cancel()
        with suppress(asyncio.CancelledError):
            await heartbeat_task
    return True


async def run_forever(interval_seconds: float = 5.0) -> None:
    while True:
        processed = await process_one_job()
        if not processed:
            await asyncio.sleep(interval_seconds)


def main() -> None:
    parser = argparse.ArgumentParser(description="AI customer service durable job worker")
    parser.add_argument("--once", action="store_true", help="process at most one job")
    parser.add_argument("--interval", type=float, default=5.0)
    arguments = parser.parse_args()
    if arguments.once:
        asyncio.run(process_one_job())
    else:
        asyncio.run(run_forever(arguments.interval))


if __name__ == "__main__":
    main()
