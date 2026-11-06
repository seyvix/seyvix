from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
import secrets
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import parse_qsl

import jwt

from app.core.config import get_settings
from app.core.logging import get_logger

logger = get_logger(__name__)

# Telegram signs OIDC id_tokens with RS256. Never trust the token header for the algorithm.
TELEGRAM_OIDC_ALGORITHM = "RS256"
_TELEGRAM_USERNAME_RE = re.compile(r"^[a-z0-9_]{3,32}$")


def normalize_telegram_username(value: str | None) -> str | None:
    """`@Some_Name` -> `some_name`; raises ValueError for strings Telegram would not accept."""
    if value is None:
        return None
    normalized = value.strip().removeprefix("@").casefold()
    if not normalized:
        return None
    if not _TELEGRAM_USERNAME_RE.fullmatch(normalized):
        raise ValueError("Telegram username must be 3-32 characters: letters, digits, underscore.")
    return normalized


@dataclass(frozen=True, slots=True)
class TelegramIdentity:
    """A Telegram account whose identity was verified by one of the login methods."""

    telegram_id: int
    first_name: str
    last_name: str | None = None
    username: str | None = None
    photo_url: str | None = None
    display_name: str | None = None

    def resolved_display_name(self) -> str:
        if self.display_name and self.display_name.strip():
            return self.display_name.strip()[:255]
        full_name = " ".join(
            part.strip() for part in (self.first_name, self.last_name) if part and part.strip()
        )
        if full_name:
            return full_name[:255]
        if self.username:
            return self.username[:255]
        return str(self.telegram_id)


def generate_token() -> str:
    return secrets.token_urlsafe(48)


def hash_token(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def tokens_equal(left: str | None, right: str | None) -> bool:
    """Constant-time comparison; empty/missing values never match."""
    if not left or not right:
        return False
    return hmac.compare_digest(left.encode("utf-8"), right.encode("utf-8"))


def build_pkce_code_challenge(code_verifier: str) -> str:
    digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def find_jwk(jwks: Mapping[str, object], kid: str) -> dict[str, Any] | None:
    keys = jwks.get("keys")
    if not isinstance(keys, list):
        return None
    for key in keys:
        if isinstance(key, dict) and key.get("kid") == kid:
            return key
    return None


def unverified_kid(id_token: str) -> str | None:
    try:
        kid = jwt.get_unverified_header(id_token).get("kid")
    except jwt.PyJWTError:
        return None
    return kid if isinstance(kid, str) and kid else None


def verify_telegram_oidc_id_token(
    id_token: str,
    *,
    jwks: Mapping[str, object],
    client_id: str,
    issuer: str,
) -> dict[str, Any] | None:
    kid = unverified_kid(id_token)
    if kid is None:
        logger.warning("auth.oidc.id_token_without_kid")
        return None
    raw_key = find_jwk(jwks, kid)
    if raw_key is None:
        logger.warning("auth.oidc.unknown_kid", kid=kid)
        return None
    key_alg = raw_key.get("alg")
    if key_alg is not None and key_alg != TELEGRAM_OIDC_ALGORITHM:
        logger.warning("auth.oidc.unexpected_key_alg", kid=kid, alg=key_alg)
        return None
    try:
        jwk = jwt.PyJWK.from_dict(raw_key, algorithm=TELEGRAM_OIDC_ALGORITHM)
        claims: dict[str, Any] = jwt.decode(
            id_token,
            key=jwk.key,
            algorithms=[TELEGRAM_OIDC_ALGORITHM],
            audience=client_id,
            issuer=issuer,
            options={"require": ["exp", "iat", "iss", "aud", "sub"]},
        )
    except jwt.PyJWTError as exc:
        logger.warning("auth.oidc.id_token_invalid", error=type(exc).__name__)
        return None
    return claims


def verify_telegram_login_data(
    data: Mapping[str, object],
    *,
    bot_token: str,
    max_age_seconds: int,
) -> bool:
    """Login Widget / tgAuthResult signature check (HMAC-SHA256 keyed by sha256(bot_token))."""
    received_hash = data.get("hash")
    if not isinstance(received_hash, str) or not received_hash:
        return False
    check_data = {key: value for key, value in data.items() if key != "hash" and value is not None}
    check_string = "\n".join(f"{key}={value}" for key, value in sorted(check_data.items()))
    secret_key = hashlib.sha256(bot_token.encode("utf-8")).digest()
    expected_hash = hmac.new(secret_key, check_string.encode("utf-8"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected_hash, received_hash):
        return False
    return _auth_date_is_fresh(data.get("auth_date"), max_age_seconds=max_age_seconds)


def parse_telegram_web_app_init_data(
    init_data: str,
    *,
    bot_token: str,
    max_age_seconds: int,
) -> TelegramIdentity | None:
    """Verify `Telegram.WebApp.initData` and return the signed-in user."""
    data = dict(parse_qsl(init_data, keep_blank_values=True))
    received_hash = data.pop("hash", "")
    if not received_hash:
        return None
    check_string = "\n".join(f"{key}={value}" for key, value in sorted(data.items()))
    secret_key = hmac.new(b"WebAppData", bot_token.encode("utf-8"), hashlib.sha256).digest()
    expected_hash = hmac.new(secret_key, check_string.encode("utf-8"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected_hash, received_hash):
        return None
    if not _auth_date_is_fresh(data.get("auth_date"), max_age_seconds=max_age_seconds):
        return None
    try:
        user = json.loads(data["user"])
    except (KeyError, ValueError):
        return None
    if not isinstance(user, dict):
        return None
    telegram_id = user.get("id")
    first_name = user.get("first_name")
    if not isinstance(telegram_id, int) or isinstance(telegram_id, bool) or telegram_id <= 0:
        return None
    if not isinstance(first_name, str) or not first_name.strip():
        return None
    return TelegramIdentity(
        telegram_id=telegram_id,
        first_name=first_name,
        last_name=_optional_str(user.get("last_name")),
        username=_optional_str(user.get("username")),
        photo_url=_optional_str(user.get("photo_url")),
    )


def _auth_date_is_fresh(value: object, *, max_age_seconds: int) -> bool:
    try:
        auth_date = datetime.fromtimestamp(int(str(value)), UTC)
    except (TypeError, ValueError, OverflowError, OSError):
        return False
    age_seconds = (datetime.now(UTC) - auth_date).total_seconds()
    # Small negative skew tolerated: Telegram's clock may be slightly ahead of ours.
    return -60 <= age_seconds <= max_age_seconds


def _optional_str(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


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
    return jwt.encode(payload, settings.auth_jwt_secret, algorithm=settings.auth_jwt_algorithm)


def decode_access_token(token: str) -> tuple[str, str] | None:
    """Return `(user_id, session_id)` for a valid access token, else None."""
    settings = get_settings()
    try:
        payload = jwt.decode(
            token,
            settings.auth_jwt_secret,
            algorithms=[settings.auth_jwt_algorithm],
            options={"require": ["exp", "sub", "sid"]},
        )
    except jwt.PyJWTError:
        return None
    user_id, session_id = payload.get("sub"), payload.get("sid")
    if payload.get("type") != "access" or not isinstance(user_id, str):
        return None
    if not isinstance(session_id, str):
        return None
    return user_id, session_id
