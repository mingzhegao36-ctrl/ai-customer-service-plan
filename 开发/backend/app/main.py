from __future__ import annotations

import secrets
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from app.api.v1.router import api_router, health_router
from app.core.config import settings
from app.core.db import AsyncSessionFactory, ensure_schema
from app.core.errors import AppError
from app.core.journal_db import ensure_journal_schema
from app.core.request_id import get_request_id, request_id_context
from app.core.security import hash_password
from app.deletion_recovery import recover_deletion_journal
from app.models import User, Workspace


@asynccontextmanager
async def lifespan(app: FastAPI):
    if settings.app_env != "development":
        if len(settings.secret_key) < 32 or settings.secret_key in {"replace-me"}:
            raise RuntimeError("production requires a random secret key of at least 32 characters")
        if not settings.provider_key_encryption_key:
            raise RuntimeError("production requires a separate provider key encryption key")
        if not settings.cookie_secure:
            raise RuntimeError("production requires secure session cookies")
        if settings.database_url.startswith("sqlite") or settings.journal_database_url.startswith(
            "sqlite"
        ):
            raise RuntimeError("production requires separately configured PostgreSQL databases")
        if settings.database_url == settings.journal_database_url:
            raise RuntimeError("business and deletion journal databases must be separate")
    await ensure_schema()
    await ensure_journal_schema()
    await recover_deletion_journal()
    if settings.bootstrap_enabled:
        if settings.app_env != "development":
            raise RuntimeError("bootstrap is allowed only in development")
        if settings.bootstrap_admin_password in {"change-me-please", "replace-with-strong-password"}:
            raise RuntimeError("set a non-default bootstrap administrator password")
        async with AsyncSessionFactory() as session:
            workspace = (await session.execute(select(Workspace).limit(1))).scalar_one_or_none()
            if workspace is None:
                workspace = Workspace(name="default-workspace")
                session.add(workspace)
                await session.flush()

            admin = (
                await session.execute(
                    select(User).where(User.username == settings.bootstrap_admin_username.lower())
                )
            ).scalar_one_or_none()
            if admin is None:
                admin = User(
                    workspace_id=workspace.id,
                    username=settings.bootstrap_admin_username.lower(),
                    password_hash=hash_password(settings.bootstrap_admin_password),
                    role="admin",
                )
                session.add(admin)
                await session.flush()

            await session.commit()
    yield


app = FastAPI(
    title=settings.app_name,
    debug=settings.debug,
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)


app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def request_id_middleware(request: Request, call_next):
    supplied_request_id = request.headers.get(settings.request_id_header)
    request_id = (
        supplied_request_id
        if supplied_request_id
        and len(supplied_request_id) <= 128
        and supplied_request_id.isprintable()
        else secrets.token_hex(16)
    )
    with request_id_context(request_id):
        response = await call_next(request)
        response.headers[settings.request_id_header] = request_id
        if request.url.path.startswith("/api/v1"):
            response.headers["Cache-Control"] = "no-store"
        return response


@app.exception_handler(AppError)
async def app_error_handler(_request: Request, exc: AppError):
    error = {
        "code": exc.code,
        "message": exc.message,
        "request_id": get_request_id(),
        "retryable": exc.retryable,
    }
    if exc.details:
        error["details"] = exc.details
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": error},
        headers={"Cache-Control": "no-store"},
    )


@app.exception_handler(RequestValidationError)
async def validation_error_handler(_request: Request, exc: RequestValidationError):
    return JSONResponse(
        status_code=422,
        content={
            "error": {
                "code": "validation_error",
                "message": str(exc),
                "request_id": get_request_id(),
                "retryable": False,
            }
        },
    )


@app.exception_handler(SQLAlchemyError)
async def sqlalchemy_error_handler(_request: Request, _exc: SQLAlchemyError):
    return JSONResponse(
        status_code=503,
        content={
            "error": {
                "code": "dependency_unavailable",
                "message": "database dependency unavailable",
                "request_id": get_request_id(),
                "retryable": True,
            }
        },
        headers={"Cache-Control": "no-store"},
    )


app.include_router(api_router, prefix="/api/v1")
app.include_router(health_router)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host="127.0.0.1", port=8000, reload=settings.debug)
