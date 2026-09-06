from __future__ import annotations

from fastapi import APIRouter

from app.api.v1.endpoints import (
    assistants,
    auth,
    billing,
    conversations,
    health,
    jobs,
    providers,
    stubs,
    workspace,
)

api_router = APIRouter()

api_router.include_router(auth.router, tags=["auth"], prefix="/auth")
api_router.include_router(workspace.router, tags=["workspace"])
api_router.include_router(providers.router, tags=["provider-connections"])
api_router.include_router(assistants.router, tags=["assistants"])
api_router.include_router(assistants.versions_router, tags=["assistant-versions"])
api_router.include_router(billing.router, tags=["billing"])
api_router.include_router(conversations.router, tags=["conversations"])
api_router.include_router(conversations.runs_router, tags=["runs"])
api_router.include_router(jobs.router, tags=["jobs"])
api_router.include_router(stubs.router, tags=["placeholders"])

health_router = health.router
