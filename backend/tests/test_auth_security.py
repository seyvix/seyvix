import hashlib
import hmac
import json
from datetime import UTC, datetime
from urllib.parse import urlencode

from app.modules.auth.security import parse_telegram_web_app_init_data

TELEGRAM_BOT_TOKEN = "123456:test-bot-token"


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
