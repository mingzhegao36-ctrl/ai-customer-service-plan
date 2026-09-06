from __future__ import annotations

import hashlib
import hmac
import json
import secrets
from base64 import urlsafe_b64decode, urlsafe_b64encode
from datetime import UTC, datetime

from cryptography.fernet import Fernet, InvalidToken
from passlib.context import CryptContext

from app.core.config import settings

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(raw: str) -> str:
    return pwd_context.hash(raw)


def verify_password(raw: str, hashed: str) -> bool:
    return pwd_context.verify(raw, hashed)


def hash_session_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def generate_token() -> str:
    return secrets.token_urlsafe(32)


def utc_now() -> datetime:
    return datetime.now(UTC)


def ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def constant_compare(a: str, b: str) -> bool:
    return secrets.compare_digest(a, b)


def request_digest(payload: object) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def encode_cursor(payload: dict[str, object], secret_key: str) -> str:
    body = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    signature = hmac.new(secret_key.encode("utf-8"), body, hashlib.sha256).digest()
    return urlsafe_b64encode(body + signature).decode("ascii").rstrip("=")


def decode_cursor(value: str, secret_key: str) -> dict[str, object]:
    padded = value + "=" * (-len(value) % 4)
    raw = urlsafe_b64decode(padded.encode("ascii"))
    if len(raw) <= 32:
        raise ValueError("invalid cursor")
    body, supplied = raw[:-32], raw[-32:]
    expected = hmac.new(secret_key.encode("utf-8"), body, hashlib.sha256).digest()
    if not hmac.compare_digest(supplied, expected):
        raise ValueError("invalid cursor")
    decoded = json.loads(body)
    if not isinstance(decoded, dict):
        raise TypeError("invalid cursor")
    return decoded


def _provider_secret_cipher() -> Fernet:
    material = settings.provider_key_encryption_key
    if not material:
        material = urlsafe_b64encode(hashlib.sha256(settings.secret_key.encode("utf-8")).digest()).decode(
            "ascii"
        )
    try:
        return Fernet(material.encode("ascii"))
    except (TypeError, ValueError) as exc:
        raise RuntimeError("provider key encryption key must be a Fernet key") from exc


def encrypt_provider_secret(value: str) -> str:
    return _provider_secret_cipher().encrypt(value.encode("utf-8")).decode("ascii")


def decrypt_provider_secret(value: str) -> str:
    try:
        return _provider_secret_cipher().decrypt(value.encode("ascii")).decode("utf-8")
    except (InvalidToken, UnicodeDecodeError) as exc:
        raise ValueError("provider secret cannot be decrypted") from exc


def provider_secret_hint(value: str) -> str:
    return f"…{value[-4:]}" if len(value) >= 4 else "configured"
