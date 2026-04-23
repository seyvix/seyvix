from __future__ import annotations

import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
from pwdlib import PasswordHash

from app.core.config import get_settings

PASSWORD_HASHER = PasswordHash.recommended()


def hash_password(password: str) -> str:
    return PASSWORD_HASHER.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    return PASSWORD_HASHER.verify(password, password_hash)


def generate_refresh_token() -> str:
    return secrets.token_urlsafe(48)


def hash_refresh_token(raw_refresh_token: str) -> str:
    return hashlib.sha256(raw_refresh_token.encode("utf-8")).hexdigest()


def build_access_token(*, user_id: str, session_id: str) -> str:
    settings = get_settings()
    now = datetime.now(UTC)
    payload: dict[str, Any] = {
        "sub": user_id,
        "sid": session_id,
        "type": "access",
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=settings.access_token_ttl_minutes)).timestamp()),
    }
    return jwt.encode(
        payload,
        settings.auth_jwt_secret,
        algorithm=settings.auth_jwt_algorithm,
    )


def decode_access_token(token: str) -> dict[str, Any]:
    settings = get_settings()
    payload = jwt.decode(
        token,
        settings.auth_jwt_secret,
        algorithms=[settings.auth_jwt_algorithm],
    )
    if payload.get("type") != "access":
        raise jwt.InvalidTokenError("invalid token type")
    return payload


def refresh_token_expires_at() -> datetime:
    settings = get_settings()
    return datetime.now(UTC) + timedelta(days=settings.refresh_token_ttl_days)
