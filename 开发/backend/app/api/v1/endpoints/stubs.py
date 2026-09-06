from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.v1.deps import get_current_user
from app.core.errors import AppError

router = APIRouter()


def _not_implemented(name: str):
    async def _handler():
        raise AppError(
            status_code=501,
            code="not_implemented",
            message=f"{name} is reserved by v1 contract and not implemented yet",
        )

    return _handler


STUBS = {
    "GET": [
        "/conversations/{conversation_id}/runs",
        "/conversations/{conversation_id}/runs/{run_id}",
        "/exports",
        "/overview",
        "/usage/turn/{turn_id}",
    ],
    "POST": [
        "/conversations/{conversation_id}/migrate-version",
        "/conversations/{conversation_id}/runs/{run_id}/retry",
        "/exports",
        "/exports/{export_id}/download",
        "/feedback",
        "/runs/{run_id}/retry",
        "/product-events",
    ],
    "PATCH": [
        "/conversations/{conversation_id}/runs/{run_id}",
    ],
    "PUT": [
    ],
    "DELETE": [
        "/assistant-versions/{assistant_version_id}",
        "/jobs/{job_id}",
        "/exports/{export_id}",
    ],
}


for method, routes in STUBS.items():
    for path in routes:
        router.add_api_route(
            path=path,
            endpoint=_not_implemented(f"{method} {path}"),
            methods=[method],
            status_code=501,
            include_in_schema=True,
            tags=["placeholders"],
            response_model=None,
            dependencies=[Depends(get_current_user)],
        )
