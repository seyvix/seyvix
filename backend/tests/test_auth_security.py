import hashlib
import hmac
import json
from datetime import UTC, datetime, timedelta
from urllib.parse import urlencode

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from jwt.algorithms import RSAAlgorithm

from app.modules.auth.security import (
    build_pkce_code_challenge,
    parse_telegram_web_app_init_data,
    verify_telegram_oidc_id_token,
)

TELEGRAM_BOT_TOKEN = "123456:test-bot-token"


def test_build_pkce_code_challenge_uses_s256_base64url() -> None:
    assert build_pkce_code_challenge(
        "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk"
    ) == "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM"


def test_verify_telegram_oidc_id_token_returns_verified_claims() -> None:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_jwk = json.loads(RSAAlgorithm.to_jwk(private_key.public_key()))
    public_jwk.update({"kid": "telegram-key", "alg": "RS256", "use": "sig"})
    now = datetime.now(UTC)
    id_token = jwt.encode(
        {
            "iss": "https://oauth.telegram.org",
            "aud": "telegram-client",
            "sub": "100500",
            "id": 100500,
            "name": "Telegram User",
            "preferred_username": "telegram_user",
            "iat": int(now.timestamp()),
            "exp": int((now + timedelta(minutes=5)).timestamp()),
        },
        private_key,
        algorithm="RS256",
        headers={"kid": "telegram-key"},
    )

    claims = verify_telegram_oidc_id_token(
        id_token,
        jwks={"keys": [public_jwk]},
        client_id="telegram-client",
        issuer="https://oauth.telegram.org",
    )

    assert claims is not None
    assert claims["id"] == 100500
    assert claims["name"] == "Telegram User"


def _signed_init_data() -> str:
    payload = {
        "query_id": "AAEAAAE",
        "user": json.dumps(
            {
                "id": 100500,
                "first_name": "Telegram",
                "last_name": "User",
                "username": "telegram_user",
                "photo_url": "https://t.me/i/userpic/320/example.jpg",
            },
            separators=(",", ":"),
        ),
        "auth_date": str(int(datetime.now(UTC).timestamp())),
    }
    check_string = "\n".join(f"{key}={value}" for key, value in sorted(payload.items()))
    secret_key = hmac.new(
        b"WebAppData",
        TELEGRAM_BOT_TOKEN.encode("utf-8"),
        hashlib.sha256,
    ).digest()
    payload["hash"] = hmac.new(
        secret_key,
        check_string.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return urlencode(payload)


def test_parse_telegram_web_app_init_data_returns_user_payload() -> None:
    payload = parse_telegram_web_app_init_data(
        _signed_init_data(),
        bot_token=TELEGRAM_BOT_TOKEN,
        max_age_seconds=86400,
    )

    assert payload["id"] == 100500
    assert payload["first_name"] == "Telegram"
    assert payload["last_name"] == "User"
    assert payload["username"] == "telegram_user"
    assert payload["photo_url"] == "https://t.me/i/userpic/320/example.jpg"


def test_parse_telegram_web_app_init_data_rejects_invalid_hash() -> None:
    init_data = _signed_init_data().replace("hash=", "hash=invalid")

    assert (
        parse_telegram_web_app_init_data(
            init_data,
            bot_token=TELEGRAM_BOT_TOKEN,
            max_age_seconds=86400,
        )
        is None
    )
