import hashlib
import hmac
import json
from datetime import UTC, datetime, timedelta
from urllib.parse import urlencode

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from jwt.algorithms import RSAAlgorithm

from app.modules.auth.security import (
    build_pkce_code_challenge,
    normalize_telegram_username,
    parse_telegram_web_app_init_data,
    tokens_equal,
    verify_telegram_login_data,
    verify_telegram_oidc_id_token,
)

TELEGRAM_BOT_TOKEN = "123456:test-bot-token"
ISSUER = "https://oauth.telegram.org"


def _rsa_key() -> tuple[rsa.RSAPrivateKey, dict[str, object]]:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_jwk = json.loads(RSAAlgorithm.to_jwk(private_key.public_key()))
    public_jwk.update({"kid": "telegram-key", "use": "sig"})
    return private_key, public_jwk


def _claims(**overrides: object) -> dict[str, object]:
    now = datetime.now(UTC)
    claims: dict[str, object] = {
        "iss": ISSUER,
        "aud": "telegram-client",
        "sub": "100500",
        "id": 100500,
        "name": "Telegram User",
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=5)).timestamp()),
    }
    claims.update(overrides)
    return claims


def test_build_pkce_code_challenge_uses_s256_base64url() -> None:
    assert (
        build_pkce_code_challenge("dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk")
        == "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM"
    )


def test_oidc_id_token_rs256_is_verified() -> None:
    private_key, public_jwk = _rsa_key()
    token = jwt.encode(_claims(), private_key, algorithm="RS256", headers={"kid": "telegram-key"})

    claims = verify_telegram_oidc_id_token(
        token,
        jwks={"keys": [public_jwk]},
        client_id="telegram-client",
        issuer=ISSUER,
    )

    assert claims is not None
    assert claims["id"] == 100500


def test_oidc_id_token_with_foreign_algorithm_is_rejected() -> None:
    _, public_jwk = _rsa_key()
    # An attacker-chosen header alg (HS256 keyed with public data) must never be honoured.
    token = jwt.encode(
        _claims(),
        "not-the-rsa-key-but-long-enough-32b",
        algorithm="HS256",
        headers={"kid": "telegram-key"},
    )

    assert (
        verify_telegram_oidc_id_token(
            token,
            jwks={"keys": [public_jwk]},
            client_id="telegram-client",
            issuer=ISSUER,
        )
        is None
    )


def test_oidc_id_token_with_wrong_audience_or_unknown_kid_is_rejected() -> None:
    private_key, public_jwk = _rsa_key()
    wrong_audience = jwt.encode(
        _claims(aud="someone-else"), private_key, algorithm="RS256", headers={"kid": "telegram-key"}
    )
    unknown_kid = jwt.encode(_claims(), private_key, algorithm="RS256", headers={"kid": "other"})

    for token in (wrong_audience, unknown_kid, "garbage"):
        assert (
            verify_telegram_oidc_id_token(
                token,
                jwks={"keys": [public_jwk]},
                client_id="telegram-client",
                issuer=ISSUER,
            )
            is None
        )


def _widget_payload(auth_date: object) -> dict[str, object]:
    payload: dict[str, object] = {"id": 1, "first_name": "A", "auth_date": auth_date}
    check = "\n".join(f"{key}={value}" for key, value in sorted(payload.items()))
    secret = hashlib.sha256(TELEGRAM_BOT_TOKEN.encode()).digest()
    payload["hash"] = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    return payload


def test_widget_login_data_rejects_malformed_auth_date_without_crashing() -> None:
    fresh = int(datetime.now(UTC).timestamp())
    assert verify_telegram_login_data(
        _widget_payload(fresh), bot_token=TELEGRAM_BOT_TOKEN, max_age_seconds=60
    )
    assert not verify_telegram_login_data(
        _widget_payload("not-a-number"), bot_token=TELEGRAM_BOT_TOKEN, max_age_seconds=60
    )
    assert not verify_telegram_login_data(
        _widget_payload(fresh - 3600), bot_token=TELEGRAM_BOT_TOKEN, max_age_seconds=60
    )


def _signed_init_data(user: dict[str, object]) -> str:
    payload = {
        "query_id": "AAEAAAE",
        "user": json.dumps(user, separators=(",", ":")),
        "auth_date": str(int(datetime.now(UTC).timestamp())),
    }
    check = "\n".join(f"{key}={value}" for key, value in sorted(payload.items()))
    secret = hmac.new(b"WebAppData", TELEGRAM_BOT_TOKEN.encode(), hashlib.sha256).digest()
    payload["hash"] = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    return urlencode(payload)


def test_web_app_init_data_returns_identity() -> None:
    identity = parse_telegram_web_app_init_data(
        _signed_init_data({"id": 100500, "first_name": "Tg", "username": "tg_user"}),
        bot_token=TELEGRAM_BOT_TOKEN,
        max_age_seconds=86400,
    )
    assert identity is not None
    assert identity.telegram_id == 100500
    assert identity.username == "tg_user"
    assert identity.resolved_display_name() == "Tg"


def test_web_app_init_data_rejects_tampering() -> None:
    init_data = _signed_init_data({"id": 100500, "first_name": "Tg"}).replace("100500", "100501")
    assert (
        parse_telegram_web_app_init_data(
            init_data, bot_token=TELEGRAM_BOT_TOKEN, max_age_seconds=86400
        )
        is None
    )


def test_tokens_equal_is_strict() -> None:
    assert tokens_equal("abc", "abc")
    assert not tokens_equal("abc", "abd")
    assert not tokens_equal("", "")
    assert not tokens_equal(None, "abc")


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("@Some_User", "some_user"), (" name ", "name"), ("", None), (None, None)],
)
def test_normalize_telegram_username(raw: str | None, expected: str | None) -> None:
    assert normalize_telegram_username(raw) == expected


def test_normalize_telegram_username_rejects_invalid() -> None:
    with pytest.raises(ValueError):
        normalize_telegram_username("bad name!")
