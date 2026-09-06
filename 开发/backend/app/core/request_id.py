import contextlib
from collections.abc import Iterator
from contextvars import ContextVar
from datetime import UTC, datetime

_request_id_ctx: ContextVar[str | None] = ContextVar("request_id", default=None)


def set_request_id(request_id: str) -> Iterator[None]:
    token = _request_id_ctx.set(request_id)
    try:
        yield None
    finally:
        _request_id_ctx.reset(token)


def get_request_id() -> str:
    current = _request_id_ctx.get()
    if current:
        return current
    fallback = datetime.now(tz=UTC).strftime("fallback-%Y%m%d%H%M%S")
    _request_id_ctx.set(fallback)
    return fallback


@contextlib.contextmanager
def request_id_context(request_id: str):
    token = _request_id_ctx.set(request_id)
    try:
        yield
    finally:
        _request_id_ctx.reset(token)
