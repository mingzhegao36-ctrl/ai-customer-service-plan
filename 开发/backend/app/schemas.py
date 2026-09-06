from __future__ import annotations

from decimal import Decimal
from typing import Any, Literal

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class LoginIn(StrictModel):
    username: str = Field(min_length=1, max_length=80)
    password: str = Field(min_length=8, max_length=128)
    remember_me: bool = False

    @field_validator("username")
    @classmethod
    def normalize_username(cls, value: str) -> str:
        normalized = value.strip().lower()
        if not normalized:
            raise ValueError("username cannot be empty")
        return normalized


class WorkspacePatchIn(StrictModel):
    name: str = Field(min_length=1, max_length=128)
    expected_revision: int = Field(ge=1)


class ServiceModePatchIn(StrictModel):
    mode: Literal["open", "service_closed"]
    expected_epoch: int = Field(ge=1)
    reason: str | None = Field(default=None, max_length=1000)


class MessageCreateIn(StrictModel):
    content: str = Field(
        min_length=1,
        max_length=8192,
        validation_alias=AliasChoices("content", "text"),
    )
    client_message_id: str = Field(min_length=1, max_length=64)
    expected_conversation_revision: int = Field(ge=1)

    @field_validator("content")
    @classmethod
    def reject_blank_content(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("content cannot be blank")
        return value


class ConversationCreateIn(StrictModel):
    assistant_id: str | None = Field(default=None, max_length=36)
    subject: str | None = Field(default=None, min_length=1, max_length=128)


class ConversationPatchIn(StrictModel):
    subject: str = Field(min_length=1, max_length=128)
    expected_revision: int = Field(ge=1)


class DeploymentIn(StrictModel):
    model_id: str = Field(min_length=1, max_length=256)
    currency: str = Field(min_length=3, max_length=3)
    input_price_per_million: Decimal = Field(ge=0)
    output_price_per_million: Decimal = Field(ge=0)
    max_input_tokens: int = Field(ge=1, le=1_000_000)
    max_output_tokens: int = Field(ge=1, le=100_000)

    @field_validator("model_id")
    @classmethod
    def normalize_model_id(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("model_id cannot be blank")
        return normalized

    @field_validator("currency")
    @classmethod
    def normalize_currency(cls, value: str) -> str:
        normalized = value.strip().upper()
        if len(normalized) != 3 or not normalized.isalpha():
            raise ValueError("currency must be a three-letter ISO code")
        return normalized


class ProviderConnectionCreateIn(StrictModel):
    name: str = Field(min_length=1, max_length=128)
    provider: Literal["openai_compatible"]
    base_url: str = Field(min_length=8, max_length=512)
    secret: str = Field(min_length=1, max_length=8192)
    deployments: list[DeploymentIn] = Field(min_length=1, max_length=20)

    @field_validator("name", "base_url")
    @classmethod
    def normalize_connection_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("connection field cannot be blank")
        return normalized


class ProviderConnectionPatchIn(StrictModel):
    expected_revision: int = Field(ge=1)
    name: str | None = Field(default=None, min_length=1, max_length=128)
    base_url: str | None = Field(default=None, min_length=8, max_length=512)
    secret: str | None = Field(default=None, min_length=1, max_length=8192)
    deployments: list[DeploymentIn] | None = Field(default=None, min_length=1, max_length=20)

    @field_validator("name", "base_url")
    @classmethod
    def normalize_optional_connection_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("connection field cannot be blank")
        return normalized


class ProviderConnectionTestIn(StrictModel):
    expected_revision: int = Field(ge=1)


class AssistantCreateIn(StrictModel):
    name: str = Field(min_length=1, max_length=128)
    description: str | None = Field(default=None, max_length=1000)


class AssistantPatchIn(StrictModel):
    expected_revision: int = Field(ge=1)
    name: str | None = Field(default=None, min_length=1, max_length=128)
    description: str | None = Field(default=None, max_length=1000)


class AssistantVersionCreateIn(StrictModel):
    deployment_id: str = Field(min_length=1, max_length=36)
    prompt: str = Field(min_length=1, max_length=32_000)
    policy_version: int = Field(ge=1)

    @field_validator("prompt")
    @classmethod
    def reject_blank_prompt(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("prompt cannot be blank")
        return value


class RevisionActionIn(StrictModel):
    expected_revision: int = Field(ge=1)
    reason: str = Field(min_length=1, max_length=1000)


class DefaultVersionIn(RevisionActionIn):
    version_id: str = Field(min_length=1, max_length=36)


class RollbackIn(RevisionActionIn):
    problem_version_id: str = Field(min_length=1, max_length=36)
    target_version_id: str = Field(min_length=1, max_length=36)


class BudgetPolicyPutIn(StrictModel):
    expected_revision: int = Field(ge=0)
    currency: str = Field(min_length=3, max_length=3)
    workspace_daily_limit: Decimal = Field(ge=0)
    workspace_monthly_limit: Decimal = Field(ge=0)
    conversation_limit: Decimal = Field(ge=0)
    turn_limit: Decimal = Field(ge=0)
    max_attempts_per_turn: int = Field(ge=1, le=10)
    max_input_tokens: int = Field(ge=1, le=1_000_000)
    max_output_tokens: int = Field(ge=1, le=100_000)
    reason: str = Field(min_length=1, max_length=1000)

    @field_validator("currency")
    @classmethod
    def normalize_policy_currency(cls, value: str) -> str:
        normalized = value.strip().upper()
        if len(normalized) != 3 or not normalized.isalpha():
            raise ValueError("currency must be a three-letter ISO code")
        return normalized


class Envelope(BaseModel):
    request_id: str
    data: Any
