from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any, Mapping

import jwt

from app.core.config import get_settings


def generate_refresh_token() -> str:
    return secrets.token_urlsafe(48)


def hash_refresh_token(raw_refresh_token: str) -> str:
    return hashlib.sha256(raw_refresh_token.encode("utf-8")).hexdigest()


def verify_telegram_login_data(
    data: Mapping[str, object],
    *,
    bot_token: str,
    max_age_seconds: int,
) -> bool:
    received_hash = str(data.get("hash", ""))
    check_data = {key: value for key, value in data.items() if key != "hash" and value is not None}
    check_string = "\n".join(f"{key}={value}" for key, value in sorted(check_data.items()))
    secret_key = hashlib.sha256(bot_token.encode("utf-8")).digest()
    expected_hash = hmac.new(
        secret_key,
        check_string.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()

    if not hmac.compare_digest(expected_hash, received_hash):
        return False

    auth_date = datetime.fromtimestamp(int(data["auth_date"]), UTC)
    age_seconds = (datetime.now(UTC) - auth_date).total_seconds()
    return 0 <= age_seconds <= max_age_seconds


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
