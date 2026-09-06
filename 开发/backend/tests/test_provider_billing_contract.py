from __future__ import annotations

import asyncio
import json
import threading
from decimal import Decimal
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from uuid import uuid4

from fastapi.testclient import TestClient

from app.core.config import settings
from app.main import app
from app.worker import process_one_job

ORIGIN = "http://127.0.0.1:4173"
PROVIDER_SECRET = "provider-test-secret"


class _ProviderHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, _format: str, *_args: Any) -> None:
        return

    def _authorized(self) -> bool:
        return self.headers.get("Authorization") == f"Bearer {PROVIDER_SECRET}"

    def _write_json(self, status_code: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Connection", "close")
        self.send_header("X-Request-ID", "provider-request-1")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        if not self._authorized():
            self._write_json(401, {"error": "invalid key"})
            return
        if self.path == "/v1/models":
            self._write_json(200, {"data": [{"id": "test-chat-model"}]})
            return
        self._write_json(404, {"error": "not found"})

    def do_POST(self) -> None:  # noqa: N802
        if not self._authorized():
            self._write_json(401, {"error": "invalid key"})
            return
        if self.path != "/v1/chat/completions":
            self._write_json(404, {"error": "not found"})
            return
        body = self.rfile.read(int(self.headers.get("Content-Length", "0")))
        request = json.loads(body)
        if request.get("model") != "test-chat-model":
            self._write_json(400, {"error": "wrong model"})
            return
        if request.get("stream"):
            chunks = [
                {"choices": [{"delta": {"content": "provider "}}]},
                {
                    "choices": [{"delta": {"content": "reply"}}],
                    "usage": {"prompt_tokens": 12, "completion_tokens": 2},
                },
            ]
            encoded = "".join(f"data: {json.dumps(item)}\n\n" for item in chunks) + "data: [DONE]\n\n"
            payload = encoded.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Connection", "close")
            self.send_header("X-Request-ID", "provider-request-stream")
            self.end_headers()
            self.wfile.write(payload)
            return
        self._write_json(
            200,
            {
                "choices": [{"message": {"content": "provider reply"}}],
                "usage": {"prompt_tokens": 12, "completion_tokens": 2},
            },
        )


def _login(client: TestClient) -> str:
    csrf = client.get("/api/v1/auth/csrf").json()["data"]["csrf_token"]
    response = client.post(
        "/api/v1/auth/login",
        headers={"Origin": ORIGIN, "x-csrf-token": csrf},
        json={"username": "admin", "password": "test-admin-password"},
    )
    assert response.status_code == 200
    return response.json()["data"]["session"]["csrf_token"]


def _write_headers(csrf: str, key: str) -> dict[str, str]:
    return {"Origin": ORIGIN, "x-csrf-token": csrf, "Idempotency-Key": key}


def test_provider_assistant_budget_and_stream_contract() -> None:
    provider = ThreadingHTTPServer(("127.0.0.1", 0), _ProviderHandler)
    provider_thread = threading.Thread(target=provider.serve_forever, daemon=True)
    provider_thread.start()
    original_hosts = settings.provider_allowed_hosts
    original_local_http = settings.provider_allow_http_for_local_testing
    settings.provider_allowed_hosts = ["127.0.0.1"]
    settings.provider_allow_http_for_local_testing = True
    try:
        with TestClient(app) as client:
            csrf = _login(client)
            policy = client.put(
                "/api/v1/budget-policies/current",
                headers=_write_headers(csrf, "unused-policy-key"),
                json={
                    "expected_revision": 0,
                    "currency": "USD",
                    "workspace_daily_limit": "2.00000000",
                    "workspace_monthly_limit": "5.00000000",
                    "conversation_limit": "1.00000000",
                    "turn_limit": "0.50000000",
                    "max_attempts_per_turn": 3,
                    "max_input_tokens": 1000,
                    "max_output_tokens": 100,
                    "reason": "bounded provider contract test",
                },
            )
            assert policy.status_code == 200
            assert policy.json()["data"]["version"] == 1

            connection = client.post(
                "/api/v1/provider-connections",
                headers=_write_headers(csrf, "unused-connection-key"),
                json={
                    "name": f"test-provider-{uuid4()}",
                    "provider": "openai_compatible",
                    "base_url": f"http://127.0.0.1:{provider.server_port}/v1",
                    "secret": PROVIDER_SECRET,
                    "deployments": [
                        {
                            "model_id": "test-chat-model",
                            "currency": "USD",
                            "input_price_per_million": "10.00000000",
                            "output_price_per_million": "20.00000000",
                            "max_input_tokens": 1000,
                            "max_output_tokens": 100,
                        }
                    ],
                },
            )
            assert connection.status_code == 201
            assert PROVIDER_SECRET not in connection.text
            connection_data = connection.json()["data"]
            connection_id = connection_data["id"]
            deployment_id = connection_data["deployments"][0]["id"]

            assistant = client.post(
                "/api/v1/assistants",
                headers=_write_headers(csrf, "unused-assistant-key"),
                json={"name": f"test assistant {uuid4()}", "description": "provider contract"},
            )
            assert assistant.status_code == 201
            assistant_data = assistant.json()["data"]
            assistant_id = assistant_data["id"]
            version = client.post(
                f"/api/v1/assistants/{assistant_id}/versions",
                headers=_write_headers(csrf, "unused-version-key"),
                json={
                    "deployment_id": deployment_id,
                    "prompt": "Answer concisely.",
                    "policy_version": 1,
                },
            )
            assert version.status_code == 201
            version_data = version.json()["data"]
            unavailable_activation = client.post(
                f"/api/v1/assistant-versions/{version_data['id']}/activate",
                headers=_write_headers(csrf, "unused-early-activate-key"),
                json={"expected_revision": version_data["revision"], "reason": "await provider test"},
            )
            assert unavailable_activation.status_code == 409

            queued = client.post(
                f"/api/v1/provider-connections/{connection_id}/test",
                headers=_write_headers(csrf, "provider-test-1"),
                json={"expected_revision": 1},
            )
            assert queued.status_code == 202
            job_id = queued.json()["data"]["job_id"]
            for _ in range(5):
                job = client.get(f"/api/v1/jobs/{job_id}")
                if job.json()["data"]["status"] != "queued":
                    break
                assert asyncio.run(process_one_job()) is True
            assert job.json()["data"]["status"] == "completed"
            assert client.get(f"/api/v1/provider-connections/{connection_id}").json()["data"]["status"] == "ready"

            activated = client.post(
                f"/api/v1/assistant-versions/{version_data['id']}/activate",
                headers=_write_headers(csrf, "unused-activate-key"),
                json={"expected_revision": version_data["revision"], "reason": "test activation"},
            )
            assert activated.status_code == 200
            defaulted = client.put(
                f"/api/v1/assistants/{assistant_id}/default-version",
                headers=_write_headers(csrf, "unused-default-key"),
                json={
                    "expected_revision": assistant_data["revision"],
                    "version_id": version_data["id"],
                    "reason": "test default",
                },
            )
            assert defaulted.status_code == 200
            defaulted_data = defaulted.json()["data"]

            replacement_version = client.post(
                f"/api/v1/assistants/{assistant_id}/versions",
                headers=_write_headers(csrf, "unused-replacement-version-key"),
                json={
                    "deployment_id": deployment_id,
                    "prompt": "Answer with a short confirmation.",
                    "policy_version": 1,
                },
            )
            assert replacement_version.status_code == 201
            replacement_data = replacement_version.json()["data"]
            assert (
                client.post(
                    f"/api/v1/assistant-versions/{replacement_data['id']}/activate",
                    headers=_write_headers(csrf, "unused-replacement-activate-key"),
                    json={"expected_revision": replacement_data["revision"], "reason": "test replacement"},
                ).status_code
                == 200
            )
            replacement_default = client.put(
                f"/api/v1/assistants/{assistant_id}/default-version",
                headers=_write_headers(csrf, "unused-replacement-default-key"),
                json={
                    "expected_revision": defaulted_data["revision"],
                    "version_id": replacement_data["id"],
                    "reason": "test replacement default",
                },
            )
            assert replacement_default.status_code == 200
            rollback = client.post(
                f"/api/v1/assistants/{assistant_id}/rollback",
                headers=_write_headers(csrf, "unused-rollback-key"),
                json={
                    "expected_revision": replacement_default.json()["data"]["revision"],
                    "problem_version_id": replacement_data["id"],
                    "target_version_id": version_data["id"],
                    "reason": "test rollback",
                },
            )
            assert rollback.status_code == 200
            assert rollback.json()["data"]["default_version_id"] == version_data["id"]

            conversation = client.post(
                "/api/v1/conversations",
                headers=_write_headers(csrf, "bound-conversation"),
                json={"subject": "provider message", "assistant_id": assistant_id},
            )
            assert conversation.status_code == 201
            conversation_data = conversation.json()["data"]
            response = client.post(
                f"/api/v1/conversations/{conversation_data['id']}/messages",
                headers=_write_headers(csrf, "unused-message-key"),
                json={
                    "content": "hello provider",
                    "client_message_id": "provider-message-1",
                    "expected_conversation_revision": conversation_data["revision"],
                },
            )
            assert response.status_code == 200
            assert response.json()["data"]["visible_text"] == "provider reply"

            usage = client.get("/api/v1/usage")
            assert usage.status_code == 200
            assert usage.json()["data"]["items"][0]["usage"]["quality"] == "actual"
            accounts = client.get("/api/v1/budget-policies/current").json()["data"]["accounts"]
            assert any(Decimal(item["spent"]) > 0 for item in accounts)
            assert all(Decimal(item["held"]) == 0 for item in accounts)

            stream_conversation = client.post(
                "/api/v1/conversations",
                headers=_write_headers(csrf, "bound-stream-conversation"),
                json={"subject": "provider stream", "assistant_id": assistant_id},
            ).json()["data"]
            with client.stream(
                "POST",
                f"/api/v1/conversations/{stream_conversation['id']}/messages:stream",
                headers=_write_headers(csrf, "unused-stream-key"),
                json={
                    "content": "stream provider",
                    "client_message_id": "provider-stream-1",
                    "expected_conversation_revision": stream_conversation["revision"],
                },
            ) as streamed:
                assert streamed.status_code == 200
                body = "".join(streamed.iter_text())
            assert "event: answer.delta" in body
            assert "event: run.completed" in body
    finally:
        settings.provider_allowed_hosts = original_hosts
        settings.provider_allow_http_for_local_testing = original_local_http
        provider.shutdown()
        provider.server_close()
        provider_thread.join(timeout=5)
