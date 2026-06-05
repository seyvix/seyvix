from __future__ import annotations

import hashlib
import hmac
import json
import secrets
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import parse_qsl

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

    auth_date = datetime.fromtimestamp(int(str(data["auth_date"])), UTC)
    age_seconds = (datetime.now(UTC) - auth_date).total_seconds()
    return 0 <= age_seconds <= max_age_seconds


def parse_telegram_web_app_init_data(
    init_data: str,
    *,
    bot_token: str,
    max_age_seconds: int,
) -> dict[str, object] | None:
    data = dict(parse_qsl(init_data, keep_blank_values=True))
    received_hash = data.get("hash", "")
    if not received_hash:
        return None

    check_data = {key: value for key, value in data.items() if key != "hash"}
    check_string = "\n".join(f"{key}={value}" for key, value in sorted(check_data.items()))
    secret_key = hmac.new(
        b"WebAppData",
        bot_token.encode("utf-8"),
        hashlib.sha256,
    ).digest()
    expected_hash = hmac.new(
        secret_key,
        check_string.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    if not hmac.compare_digest(expected_hash, received_hash):
        return None

    try:
        auth_date = datetime.fromtimestamp(int(data["auth_date"]), UTC)
    except (KeyError, TypeError, ValueError, OSError):
        return None
    age_seconds = (datetime.now(UTC) - auth_date).total_seconds()
    if age_seconds < 0 or age_seconds > max_age_seconds:
        return None

    try:
        user_data = json_loads_dict(data["user"])
    except (KeyError, TypeError, ValueError):
        return None

    return {
        "id": user_data.get("id"),
        "first_name": user_data.get("first_name"),
        "last_name": user_data.get("last_name"),
        "username": user_data.get("username"),
        "photo_url": user_data.get("photo_url"),
    }


def json_loads_dict(value: str) -> dict[str, object]:
    parsed = json.loads(value)
    if not isinstance(parsed, dict):
        raise ValueError("expected object")
    return parsed


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
