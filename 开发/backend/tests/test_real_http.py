from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx

ORIGIN = "http://127.0.0.1:4173"
PROVIDER_SECRET = "real-http-provider-secret"


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
        self.send_header("X-Request-ID", "real-http-provider-request")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        if not self._authorized():
            self._write_json(401, {"error": "invalid key"})
            return
        if self.path == "/v1/models":
            self._write_json(200, {"data": [{"id": "real-http-chat-model"}]})
            return
        self._write_json(404, {"error": "not found"})

    def do_POST(self) -> None:  # noqa: N802
        if not self._authorized():
            self._write_json(401, {"error": "invalid key"})
            return
        if self.path != "/v1/chat/completions":
            self._write_json(404, {"error": "not found"})
            return
        request = json.loads(self.rfile.read(int(self.headers.get("Content-Length", "0"))))
        if request.get("model") != "real-http-chat-model":
            self._write_json(400, {"error": "wrong model"})
            return
        if request.get("stream"):
            chunks = [
                {"choices": [{"delta": {"content": "real "}}]},
                {
                    "choices": [{"delta": {"content": "provider reply"}}],
                    "usage": {"prompt_tokens": 12, "completion_tokens": 2},
                },
            ]
            body = ("".join(f"data: {json.dumps(item)}\n\n" for item in chunks) + "data: [DONE]\n\n").encode(
                "utf-8"
            )
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Connection", "close")
            self.send_header("X-Request-ID", "real-http-provider-stream")
            self.end_headers()
            self.wfile.write(body)
            return
        self._write_json(
            200,
            {
                "choices": [{"message": {"content": "real provider reply"}}],
                "usage": {"prompt_tokens": 12, "completion_tokens": 2},
            },
        )


def _unused_local_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def _write_headers(csrf: str, key: str) -> dict[str, str]:
    return {"Origin": ORIGIN, "x-csrf-token": csrf, "Idempotency-Key": key}


def _process_one_worker(environment: dict[str, str]) -> None:
    subprocess.run(
        [
            sys.executable,
            "-c",
            "import asyncio; from app.worker import process_one_job; assert asyncio.run(process_one_job())",
        ],
        check=True,
        env=environment,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def test_core_contract_over_real_http() -> None:
    root = Path(tempfile.gettempdir()) / f"ai-cs-real-http-{uuid4()}"
    root.mkdir()
    provider = ThreadingHTTPServer(("127.0.0.1", 0), _ProviderHandler)
    provider_thread = threading.Thread(target=provider.serve_forever, daemon=True)
    provider_thread.start()
    port = _unused_local_port()
    environment = os.environ.copy()
    environment.update(
        {
            "AI_CS_APP_ENV": "development",
            "AI_CS_DATABASE_URL": f"sqlite+aiosqlite:///{(root / 'business.db').as_posix()}",
            "AI_CS_JOURNAL_DATABASE_URL": f"sqlite+aiosqlite:///{(root / 'journal.db').as_posix()}",
            "AI_CS_SECRET_KEY": "real-http-test-secret-at-least-thirty-two-characters",
            "AI_CS_AUTO_CREATE_SCHEMA": "true",
            "AI_CS_BOOTSTRAP_ENABLED": "true",
            "AI_CS_BOOTSTRAP_ADMIN_PASSWORD": "test-admin-password",
            "AI_CS_PROVIDER_ALLOWED_HOSTS": '["127.0.0.1"]',
            "AI_CS_PROVIDER_ALLOW_HTTP_FOR_LOCAL_TESTING": "true",
        }
    )
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "app.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
        ],
        env=environment,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    base_url = f"http://127.0.0.1:{port}"
    try:
        with httpx.Client(base_url=base_url, timeout=5, trust_env=False) as client:
            for _ in range(40):
                try:
                    if client.get("/health").status_code == 200:
                        break
                except httpx.HTTPError:
                    time.sleep(0.1)
            else:
                raise AssertionError("Uvicorn did not accept HTTP requests")
            csrf = client.get("/api/v1/auth/csrf").json()["data"]["csrf_token"]
            login = client.post(
                "/api/v1/auth/login",
                headers={"Origin": ORIGIN, "x-csrf-token": csrf},
                json={"username": "admin", "password": "test-admin-password"},
            )
            assert login.status_code == 200
            session_csrf = login.json()["data"]["session"]["csrf_token"]

            policy = client.put(
                "/api/v1/budget-policies/current",
                headers=_write_headers(session_csrf, "real-http-policy"),
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
                    "reason": "real HTTP contract test",
                },
            )
            assert policy.status_code == 200

            connection = client.post(
                "/api/v1/provider-connections",
                headers=_write_headers(session_csrf, "real-http-connection"),
                json={
                    "name": f"real-http-provider-{uuid4()}",
                    "provider": "openai_compatible",
                    "base_url": f"http://127.0.0.1:{provider.server_port}/v1",
                    "secret": PROVIDER_SECRET,
                    "deployments": [
                        {
                            "model_id": "real-http-chat-model",
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
            deployment_id = connection_data["deployments"][0]["id"]
            queued = client.post(
                f"/api/v1/provider-connections/{connection_data['id']}/test",
                headers=_write_headers(session_csrf, "real-http-provider-test"),
                json={"expected_revision": connection_data["revision"]},
            )
            assert queued.status_code == 202
            job_id = queued.json()["data"]["job_id"]
            _process_one_worker(environment)
            for _ in range(20):
                job = client.get(f"/api/v1/jobs/{job_id}")
                if job.json()["data"]["status"] != "queued":
                    break
                time.sleep(0.1)
            assert job.json()["data"]["status"] == "completed"

            assistant = client.post(
                "/api/v1/assistants",
                headers=_write_headers(session_csrf, "real-http-assistant"),
                json={"name": f"real HTTP assistant {uuid4()}"},
            )
            assert assistant.status_code == 201
            assistant_data = assistant.json()["data"]
            version = client.post(
                f"/api/v1/assistants/{assistant_data['id']}/versions",
                headers=_write_headers(session_csrf, "real-http-version"),
                json={
                    "deployment_id": deployment_id,
                    "prompt": "Answer concisely.",
                    "policy_version": 1,
                },
            )
            assert version.status_code == 201
            version_data = version.json()["data"]
            assert (
                client.post(
                    f"/api/v1/assistant-versions/{version_data['id']}/activate",
                    headers=_write_headers(session_csrf, "real-http-activate"),
                    json={"expected_revision": version_data["revision"], "reason": "real HTTP activation"},
                ).status_code
                == 200
            )
            assert (
                client.put(
                    f"/api/v1/assistants/{assistant_data['id']}/default-version",
                    headers=_write_headers(session_csrf, "real-http-default"),
                    json={
                        "expected_revision": assistant_data["revision"],
                        "version_id": version_data["id"],
                        "reason": "real HTTP default",
                    },
                ).status_code
                == 200
            )

            conversation = client.post(
                "/api/v1/conversations",
                headers=_write_headers(session_csrf, "real-http-conversation"),
                json={"subject": "real HTTP", "assistant_id": assistant_data["id"]},
            )
            assert conversation.status_code == 201
            conversation_data = conversation.json()["data"]
            response = client.post(
                f"/api/v1/conversations/{conversation_data['id']}/messages",
                headers=_write_headers(session_csrf, "real-http-message"),
                json={
                    "content": "verify actual HTTP",
                    "client_message_id": "real-http-message",
                    "expected_conversation_revision": conversation_data["revision"],
                },
            )
            assert response.status_code == 200
            assert response.json()["data"]["visible_text"] == "real provider reply"

            stream_conversation = client.post(
                "/api/v1/conversations",
                headers=_write_headers(session_csrf, "real-http-stream-conversation"),
                json={"subject": "real HTTP stream", "assistant_id": assistant_data["id"]},
            ).json()["data"]
            with client.stream(
                "POST",
                f"/api/v1/conversations/{stream_conversation['id']}/messages:stream",
                headers=_write_headers(session_csrf, "real-http-stream"),
                json={
                    "content": "verify actual HTTP stream",
                    "client_message_id": "real-http-stream-message",
                    "expected_conversation_revision": stream_conversation["revision"],
                },
            ) as streamed:
                assert streamed.status_code == 200
                assert streamed.headers["content-type"].startswith("text/event-stream")
                body = "".join(streamed.iter_text())
            assert "event: answer.delta" in body
            assert "event: run.completed" in body
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
        provider.shutdown()
        provider.server_close()
        provider_thread.join(timeout=5)
        shutil.rmtree(root, ignore_errors=True)
