from __future__ import annotations

from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "AI Customer Service API"
    app_env: str = "development"
    debug: bool = False

    database_url: str = "sqlite+aiosqlite:///./backend-dev.db"
    journal_database_url: str = "sqlite+aiosqlite:///./journal-dev.db"

    secret_key: str = "replace-me"

    allowed_origins: list[str] = Field(
        default_factory=lambda: ["http://127.0.0.1:4173", "http://127.0.0.1:5173"]
    )
    api_origin: str = "http://127.0.0.1:8000"

    session_cookie_name: str = "cs_session"
    session_idle_ttl_minutes: int = 480
    session_absolute_ttl_hours: int = 12
    session_remember_absolute_ttl_hours: int = 168
    csrf_ttl_seconds: int = 1800
    preauth_csrf_cookie_name: str = "csrf_pre"
    cookie_secure: bool = False
    cookie_samesite: Literal["lax", "strict", "none"] = "lax"
    cookie_domain: str = ""

    workspace_tz: str = "Asia/Shanghai"
    auto_create_schema: bool = False

    bootstrap_enabled: bool = False
    bootstrap_admin_username: str = "admin"
    bootstrap_admin_password: str = "change-me-please"

    instance_id: str = "local-api-1"
    login_rate_limit_attempts: int = 10
    login_rate_limit_window_seconds: int = 300
    worker_lease_seconds: int = 30
    worker_heartbeat_seconds: int = 10
    worker_max_attempts: int = 5

    provider_allowed_hosts: list[str] = Field(default_factory=list)
    provider_allow_http_for_local_testing: bool = False
    provider_request_timeout_seconds: int = 30
    provider_key_encryption_key: str = ""

    request_id_header: str = "X-Request-ID"

    model_config = SettingsConfigDict(
        env_prefix="AI_CS_",
        env_file=".env",
        extra="ignore",
    )


settings = Settings()
