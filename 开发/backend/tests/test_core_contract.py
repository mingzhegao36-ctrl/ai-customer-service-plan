from __future__ import annotations

import asyncio
from datetime import timedelta
from uuid import uuid4

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import select  # noqa: E402

from app.core.config import settings  # noqa: E402
from app.core.db import AsyncSessionFactory  # noqa: E402
from app.core.journal_db import JournalSessionFactory  # noqa: E402
from app.core.security import request_digest, utc_now  # noqa: E402
from app.deletion_recovery import recover_deletion_journal  # noqa: E402
from app.journal_models import DeletionJournal, JournalHead  # noqa: E402
from app.main import app  # noqa: E402
from app.models import (  # noqa: E402
    Conversation,
    DeletionReceipt,
    Job,
    JournalProjection,
    User,
)
from app.worker import JobClaim, _fail_unsupported_claim, process_one_job  # noqa: E402

ORIGIN = "http://127.0.0.1:4173"


def _login(client: TestClient) -> str:
    csrf_response = client.get("/api/v1/auth/csrf")
    assert csrf_response.status_code == 200
    assert csrf_response.headers["cache-control"] == "no-store"
    pre_auth_csrf = csrf_response.json()["data"]["csrf_token"]

    denied = client.post(
        "/api/v1/auth/login",
        headers={"x-csrf-token": pre_auth_csrf},
        json={"username": "admin", "password": "test-admin-password"},
    )
    assert denied.status_code == 403

    response = client.post(
        "/api/v1/auth/login",
        headers={"Origin": ORIGIN, "x-csrf-token": pre_auth_csrf},
        json={"username": "admin", "password": "test-admin-password"},
    )
    assert response.status_code == 200
    return response.json()["data"]["session"]["csrf_token"]


def test_identity_conversation_controls_and_deletion_receipt() -> None:
    with TestClient(app) as client:
        csrf = _login(client)
        headers = {
            "Origin": ORIGIN,
            "x-csrf-token": csrf,
            "Idempotency-Key": "conversation-create-1",
        }

        first = client.post(
            "/api/v1/conversations",
            headers=headers,
            json={"subject": "Contract test"},
        )
        replay = client.post(
            "/api/v1/conversations",
            headers=headers,
            json={"subject": "Contract test"},
        )
        conflict = client.post(
            "/api/v1/conversations",
            headers=headers,
            json={"subject": "Different request"},
        )
        assert first.status_code == replay.status_code == 201
        assert first.json()["data"]["id"] == replay.json()["data"]["id"]
        assert conflict.status_code == 409
        conversation_id = first.json()["data"]["id"]

        empty_list = client.get("/api/v1/conversations")
        assert empty_list.json()["data"]["items"] == []
        assert client.get("/api/v1/conversations?limit=101").status_code == 422
        assert client.get("/api/v1/conversations?cursor=invalid").status_code == 422

        message = {
            "content": "hello",
            "client_message_id": "client-message-1",
            "expected_conversation_revision": 1,
        }
        sent = client.post(
            f"/api/v1/conversations/{conversation_id}/messages",
            headers=headers,
            json=message,
        )
        repeated = client.post(
            f"/api/v1/conversations/{conversation_id}/messages",
            headers=headers,
            json=message,
        )
        changed = client.post(
            f"/api/v1/conversations/{conversation_id}/messages",
            headers=headers,
            json={**message, "content": "different"},
        )
        assert sent.status_code == 200
        assert sent.json()["data"]["status"] == "completed"
        assert repeated.json()["data"]["replayed"] is True
        assert changed.status_code == 409
        assert len(client.get("/api/v1/conversations").json()["data"]["items"]) == 1

        closed = client.put(
            "/api/v1/service-mode",
            headers=headers,
            json={"mode": "service_closed", "expected_epoch": 1, "reason": "maintenance"},
        )
        assert closed.status_code == 200
        blocked = client.post(
            f"/api/v1/conversations/{conversation_id}/messages",
            headers=headers,
            json={
                "content": "must be blocked",
                "client_message_id": "client-message-2",
                "expected_conversation_revision": 4,
            },
        )
        assert blocked.status_code == 409
        assert blocked.json()["error"]["code"] == "service_paused"
        assert (
            client.put(
                "/api/v1/service-mode",
                headers=headers,
                json={"mode": "open", "expected_epoch": 2},
            ).status_code
            == 200
        )

        delete_headers = {**headers, "Idempotency-Key": "conversation-delete-1"}
        deleted = client.delete(
            f"/api/v1/conversations/{conversation_id}?expected_conversation_revision=4",
            headers=delete_headers,
        )
        delete_replay = client.delete(
            f"/api/v1/conversations/{conversation_id}?expected_conversation_revision=4",
            headers=delete_headers,
        )
        assert deleted.status_code == delete_replay.status_code == 202
        assert deleted.json()["data"]["receipt_id"] == delete_replay.json()["data"]["receipt_id"]
        assert (
            client.post(
                "/api/v1/conversations",
                headers=headers,
                json={"subject": "Contract test"},
            ).status_code
            == 404
        )
        job_id = deleted.json()["data"]["job_id"]
        job = client.get(f"/api/v1/jobs/{job_id}")
        assert job.status_code == 200
        assert job.json()["data"]["stage"] == "journal_confirmed"
        assert asyncio.run(process_one_job()) is True
        completed_job = client.get(f"/api/v1/jobs/{job_id}")
        assert completed_job.json()["data"]["status"] == "completed"
        assert completed_job.json()["data"]["stage"] == "online_cleanup_completed"

        assert client.post("/api/v1/auth/logout", headers={"Origin": ORIGIN}).status_code == 403
        assert (
            client.post(
                "/api/v1/auth/logout",
                headers={"Origin": ORIGIN, "x-csrf-token": csrf},
            ).status_code
            == 204
        )
        assert client.post("/api/v1/auth/logout", headers={"Origin": ORIGIN}).status_code == 204


def test_sse_first_submission_and_json_replay() -> None:
    with TestClient(app) as client:
        csrf = _login(client)
        headers = {
            "Origin": ORIGIN,
            "x-csrf-token": csrf,
            "Idempotency-Key": "stream-conversation-create",
        }
        created = client.post(
            "/api/v1/conversations",
            headers=headers,
            json={"subject": "SSE contract"},
        )
        conversation_id = created.json()["data"]["id"]
        payload = {
            "content": "stream this",
            "client_message_id": "stream-client-message",
            "expected_conversation_revision": 1,
        }
        with client.stream(
            "POST",
            f"/api/v1/conversations/{conversation_id}/messages:stream",
            headers=headers,
            json=payload,
        ) as response:
            assert response.status_code == 200
            assert response.headers["content-type"].startswith("text/event-stream")
            body = "".join(response.iter_text())
        assert "event: run.created" in body
        assert "event: answer.delta" in body
        assert "event: run.completed" in body

        replay = client.post(
            f"/api/v1/conversations/{conversation_id}/messages:stream",
            headers=headers,
            json=payload,
        )
        assert replay.status_code == 200
        assert replay.headers["content-type"].startswith("application/json")
        assert replay.json()["data"]["replayed"] is True
        assert replay.json()["data"]["visible_text"] == "Mock response: stream this"


def test_session_csrf_refresh_and_assistant_binding_contract() -> None:
    with TestClient(app) as client:
        csrf = _login(client)
        refreshed = client.get("/api/v1/auth/csrf")
        assert refreshed.status_code == 200
        assert refreshed.json()["data"]["csrf_token"] == csrf
        headers = {
            "Origin": ORIGIN,
            "x-csrf-token": refreshed.json()["data"]["csrf_token"],
            "Idempotency-Key": "csrf-refresh-create",
        }
        created = client.post("/api/v1/conversations", headers=headers, json={"subject": "Refreshed"})
        assert created.status_code == 201
        assert created.json()["data"]["assistant_id"] is None
        rejected = client.post(
            "/api/v1/conversations",
            headers={**headers, "Idempotency-Key": "assistant-binding"},
            json={"subject": "Bound", "assistant_id": str(uuid4())},
        )
        assert rejected.status_code == 409
        assert rejected.json()["error"]["code"] == "assistant_unavailable"


def test_jobs_cursor_uses_created_at_and_id_tuple() -> None:
    async def create_jobs() -> None:
        async with AsyncSessionFactory() as session:
            user = (await session.execute(select(User).where(User.username == "admin"))).scalar_one()
            now = utc_now()
            session.add_all(
                [
                    Job(
                        id="00000000-0000-0000-0000-000000000001",
                        workspace_id=user.workspace_id,
                        actor_id=user.id,
                        type="cursor-regression",
                        status="queued",
                        stage="queued",
                        created_at=now,
                        available_at=now,
                    ),
                    Job(
                        id="ffffffff-ffff-ffff-ffff-ffffffffffff",
                        workspace_id=user.workspace_id,
                        actor_id=user.id,
                        type="cursor-regression",
                        status="queued",
                        stage="queued",
                        created_at=now - timedelta(seconds=1),
                        available_at=now,
                    ),
                ]
            )
            await session.commit()

    with TestClient(app) as client:
        asyncio.run(create_jobs())
        _login(client)
        first = client.get("/api/v1/jobs?type=cursor-regression&limit=1")
        assert first.status_code == 200
        first_data = first.json()["data"]
        assert first_data["items"][0]["id"] == "00000000-0000-0000-0000-000000000001"
        second = client.get(
            "/api/v1/jobs?type=cursor-regression&limit=1&cursor=" + first_data["next_cursor"]
        )
        assert second.status_code == 200
        assert second.json()["data"]["items"][0]["id"] == "ffffffff-ffff-ffff-ffff-ffffffffffff"


def test_journal_only_entry_is_projected_and_blocks_content() -> None:
    with TestClient(app) as client:
        csrf = _login(client)
        headers = {
            "Origin": ORIGIN,
            "x-csrf-token": csrf,
            "Idempotency-Key": "journal-recovery-conversation",
        }
        created = client.post("/api/v1/conversations", headers=headers, json={"subject": "Recovery"})
        assert created.status_code == 201
        conversation_id = created.json()["data"]["id"]

        async def add_journal_only_entry() -> str:
            async with AsyncSessionFactory() as business:
                user = (await business.execute(select(User).where(User.username == "admin"))).scalar_one()
            operation_id = str(uuid4())
            digest = request_digest({"operation_id": operation_id, "conversation_id": conversation_id})
            async with JournalSessionFactory() as journal:
                head = await journal.get(JournalHead, user.workspace_id, with_for_update=True)
                if head is None:
                    head = JournalHead(workspace_id=user.workspace_id, head_seq=0)
                    journal.add(head)
                    await journal.flush()
                head.head_seq += 1
                journal.add(
                    DeletionJournal(
                        id=str(uuid4()),
                        workspace_id=user.workspace_id,
                        seq=head.head_seq,
                        operation_id=operation_id,
                        resource_type="conversation",
                        resource_id=conversation_id,
                        request_hash=digest,
                        actor_id=user.id,
                        instance_id="test-recovery",
                        payload_json="{}",
                    )
                )
                await journal.commit()
            return operation_id

        operation_id = asyncio.run(add_journal_only_entry())
        assert asyncio.run(recover_deletion_journal()) >= 1

        async def assert_projection() -> None:
            async with AsyncSessionFactory() as session:
                conversation = await session.get(Conversation, conversation_id)
                assert conversation is not None and conversation.deleted_at is not None
                receipt = (
                    await session.execute(
                        select(DeletionReceipt).where(DeletionReceipt.operation_id == operation_id)
                    )
                ).scalar_one()
                projection = await session.get(JournalProjection, receipt.workspace_id)
                assert projection is not None and projection.applied_seq >= receipt.journal_seq

        asyncio.run(assert_projection())
        assert client.get(f"/api/v1/conversations/{conversation_id}").status_code == 404


def test_readiness_rejects_create_all_schema_without_alembic_state() -> None:
    with TestClient(app) as client:
        response = client.get("/health/ready")
        assert response.status_code == 503
        assert response.json()["error"]["code"] == "migration_pending"


def test_login_rate_limit_is_persisted_and_bounded() -> None:
    original_limit = settings.login_rate_limit_attempts
    settings.login_rate_limit_attempts = 2
    try:
        with TestClient(app) as client:
            token = client.get("/api/v1/auth/csrf").json()["data"]["csrf_token"]
            headers = {"Origin": ORIGIN, "x-csrf-token": token}
            for _ in range(2):
                response = client.post(
                    "/api/v1/auth/login",
                    headers=headers,
                    json={"username": "rate-limit-user", "password": "incorrect-password"},
                )
                assert response.status_code == 401
            limited = client.post(
                "/api/v1/auth/login",
                headers=headers,
                json={"username": "rate-limit-user", "password": "incorrect-password"},
            )
            assert limited.status_code == 429
    finally:
        settings.login_rate_limit_attempts = original_limit


def test_stale_worker_claim_cannot_finalize_a_reclaimed_job() -> None:
    async def assert_stale_claim_is_rejected() -> None:
        async with AsyncSessionFactory() as session:
            user = (await session.execute(select(User).where(User.username == "admin"))).scalar_one()
            job = Job(
                workspace_id=user.workspace_id,
                actor_id=user.id,
                type="unsupported-for-fence-test",
                status="running",
                stage="claimed",
                claimed_by=settings.instance_id,
                claim_version=2,
                attempt_count=2,
                lease_expires_at=utc_now() + timedelta(seconds=30),
                available_at=utc_now(),
            )
            session.add(job)
            await session.commit()
            stale_claim = JobClaim(
                job_id=job.id,
                claim_version=1,
                claimed_by=settings.instance_id,
            )
        await _fail_unsupported_claim(stale_claim)
        async with AsyncSessionFactory() as session:
            current = await session.get(Job, stale_claim.job_id)
            assert current is not None
            assert current.status == "running"
            assert current.claim_version == 2

    with TestClient(app):
        asyncio.run(assert_stale_claim_is_rejected())
