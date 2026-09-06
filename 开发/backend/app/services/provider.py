from __future__ import annotations

import asyncio
import ipaddress
import json
import socket
from collections.abc import AsyncIterator
from dataclasses import dataclass
from urllib.parse import urlsplit

import httpx

from app.core.config import settings


class ProviderError(Exception):
    def __init__(self, code: str, *, retryable: bool, outcome_unknown: bool = False) -> None:
        self.code = code
        self.retryable = retryable
        self.outcome_unknown = outcome_unknown
        super().__init__(code)


@dataclass(frozen=True)
class ProviderUsage:
    input_tokens: int | None
    output_tokens: int | None
    provider_request_id: str | None


@dataclass(frozen=True)
class ProviderCompletion:
    text: str
    usage: ProviderUsage


@dataclass(frozen=True)
class ProviderStreamEvent:
    text: str | None
    usage: ProviderUsage | None


def _is_local_test_host(host: str) -> bool:
    return (
        settings.app_env == "development"
        and settings.provider_allow_http_for_local_testing
        and host in {item.lower() for item in settings.provider_allowed_hosts}
    )


async def validate_provider_base_url(value: str) -> str:
    parsed = urlsplit(value.strip())
    if parsed.scheme not in {"https", "http"} or not parsed.hostname:
        raise ValueError("provider base URL must be an absolute HTTP(S) URL")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("provider base URL must not include credentials, query, or fragment")
    host = parsed.hostname.lower()
    allowed_hosts = {item.lower() for item in settings.provider_allowed_hosts}
    if host not in allowed_hosts:
        raise ValueError("provider host is not approved")
    local_test_host = _is_local_test_host(host)
    if parsed.scheme != "https" and not local_test_host:
        raise ValueError("provider base URL must use HTTPS")
    if parsed.port not in {None, 443 if parsed.scheme == "https" else 80} and not local_test_host:
        raise ValueError("provider base URL uses an unapproved port")
    try:
        resolved = await asyncio.get_running_loop().getaddrinfo(host, parsed.port or 443)
    except socket.gaierror as exc:
        raise ValueError("provider host cannot be resolved") from exc
    addresses = {entry[4][0] for entry in resolved}
    if not addresses:
        raise ValueError("provider host cannot be resolved")
    for address in addresses:
        ip = ipaddress.ip_address(address)
        if not ip.is_global and not local_test_host:
            raise ValueError("provider host resolves to a non-public address")
    return parsed.geturl().rstrip("/")


async def _validated_call_base_url(base_url: str) -> str:
    try:
        return await validate_provider_base_url(base_url)
    except ValueError as exc:
        raise ProviderError("provider_target_rejected", retryable=False) from exc


def _headers(secret: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {secret}", "Accept": "application/json"}


def _provider_error(response: httpx.Response) -> ProviderError:
    if response.status_code in {401, 403}:
        return ProviderError("provider_auth_failed", retryable=False)
    if response.status_code == 429:
        return ProviderError("provider_rate_limited", retryable=True)
    if response.status_code >= 500:
        return ProviderError("provider_unavailable", retryable=True, outcome_unknown=True)
    return ProviderError("provider_request_rejected", retryable=False)


async def list_models(*, base_url: str, secret: str) -> list[str]:
    base_url = await _validated_call_base_url(base_url)
    try:
        async with httpx.AsyncClient(
            timeout=settings.provider_request_timeout_seconds,
            follow_redirects=False,
            trust_env=False,
        ) as client:
            response = await client.get(f"{base_url}/models", headers=_headers(secret))
    except httpx.TimeoutException as exc:
        raise ProviderError("provider_timeout", retryable=True, outcome_unknown=True) from exc
    except httpx.HTTPError as exc:
        raise ProviderError("provider_network_error", retryable=True, outcome_unknown=True) from exc
    if response.is_redirect:
        raise ProviderError("provider_redirect_rejected", retryable=False)
    if response.status_code != 200:
        raise _provider_error(response)
    try:
        payload = response.json()
        data = payload["data"]
        models = [item["id"] for item in data if isinstance(item, dict) and isinstance(item.get("id"), str)]
    except (KeyError, TypeError, ValueError) as exc:
        raise ProviderError("provider_response_invalid", retryable=False) from exc
    return models


def _usage(payload: object, response: httpx.Response) -> ProviderUsage:
    usage = payload.get("usage") if isinstance(payload, dict) else None
    usage = usage if isinstance(usage, dict) else {}
    prompt = usage.get("prompt_tokens")
    completion = usage.get("completion_tokens")
    return ProviderUsage(
        input_tokens=prompt if isinstance(prompt, int) and prompt >= 0 else None,
        output_tokens=completion if isinstance(completion, int) and completion >= 0 else None,
        provider_request_id=response.headers.get("x-request-id") or response.headers.get("request-id"),
    )


async def complete(
    *,
    base_url: str,
    secret: str,
    model_id: str,
    system_prompt: str,
    user_content: str,
    max_output_tokens: int,
) -> ProviderCompletion:
    base_url = await _validated_call_base_url(base_url)
    body = {
        "model": model_id,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ],
        "max_tokens": max_output_tokens,
        "stream": False,
    }
    try:
        async with httpx.AsyncClient(
            timeout=settings.provider_request_timeout_seconds,
            follow_redirects=False,
            trust_env=False,
        ) as client:
            response = await client.post(
                f"{base_url}/chat/completions",
                headers={**_headers(secret), "Content-Type": "application/json"},
                json=body,
            )
    except httpx.TimeoutException as exc:
        raise ProviderError("provider_timeout", retryable=True, outcome_unknown=True) from exc
    except httpx.HTTPError as exc:
        raise ProviderError("provider_network_error", retryable=True, outcome_unknown=True) from exc
    if response.is_redirect:
        raise ProviderError("provider_redirect_rejected", retryable=False)
    if response.status_code != 200:
        raise _provider_error(response)
    try:
        payload = response.json()
        text = payload["choices"][0]["message"]["content"]
    except (IndexError, KeyError, TypeError, ValueError) as exc:
        raise ProviderError("provider_response_invalid", retryable=False) from exc
    if not isinstance(text, str):
        raise ProviderError("provider_response_invalid", retryable=False)
    return ProviderCompletion(text=text, usage=_usage(payload, response))


async def stream_completion(
    *,
    base_url: str,
    secret: str,
    model_id: str,
    system_prompt: str,
    user_content: str,
    max_output_tokens: int,
) -> AsyncIterator[ProviderStreamEvent]:
    base_url = await _validated_call_base_url(base_url)
    body = {
        "model": model_id,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ],
        "max_tokens": max_output_tokens,
        "stream": True,
    }
    try:
        async with httpx.AsyncClient(
            timeout=settings.provider_request_timeout_seconds,
            follow_redirects=False,
            trust_env=False,
        ) as client:
            async with client.stream(
                "POST",
                f"{base_url}/chat/completions",
                headers={**_headers(secret), "Content-Type": "application/json"},
                json=body,
            ) as response:
                if response.is_redirect:
                    raise ProviderError("provider_redirect_rejected", retryable=False)
                if response.status_code != 200:
                    raise _provider_error(response)
                request_id = response.headers.get("x-request-id") or response.headers.get("request-id")
                async for line in response.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    raw = line[5:].strip()
                    if raw == "[DONE]":
                        return
                    try:
                        payload = json.loads(raw)
                    except json.JSONDecodeError as exc:
                        raise ProviderError("provider_response_invalid", retryable=False) from exc
                    usage = _usage(payload, response)
                    if usage.provider_request_id is None:
                        usage = ProviderUsage(
                            input_tokens=usage.input_tokens,
                            output_tokens=usage.output_tokens,
                            provider_request_id=request_id,
                        )
                    choice = payload.get("choices", [{}])[0] if isinstance(payload, dict) else {}
                    delta = choice.get("delta", {}) if isinstance(choice, dict) else {}
                    text = delta.get("content") if isinstance(delta, dict) else None
                    yield ProviderStreamEvent(text=text if isinstance(text, str) else None, usage=usage)
    except ProviderError:
        raise
    except httpx.TimeoutException as exc:
        raise ProviderError("provider_timeout", retryable=True, outcome_unknown=True) from exc
    except httpx.HTTPError as exc:
        raise ProviderError("provider_network_error", retryable=True, outcome_unknown=True) from exc
