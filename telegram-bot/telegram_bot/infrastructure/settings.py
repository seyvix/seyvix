from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Settings:
    telegram_bot_token: str
    telegram_api_base: str | None
    telegram_internal_token: str
    telegram_backend_base_url: str
    telegram_web_app_url: str | None
    telegram_bot_poll_timeout_seconds: int = 30
    telegram_media_group_flush_seconds: float = 1.2
    log_level: str = "INFO"


def get_settings() -> Settings:
    bot_token = _required_env("TELEGRAM_BOT_TOKEN")
    internal_token = os.getenv("TELEGRAM_INTERNAL_TOKEN") or bot_token
    return Settings(
        telegram_bot_token=bot_token,
        telegram_api_base=os.getenv("TELEGRAM_API_BASE") or None,
        telegram_internal_token=internal_token,
        telegram_backend_base_url=os.getenv(
            "TELEGRAM_BACKEND_BASE_URL",
            "http://backend:8000/api/v1",
        ).rstrip("/"),
        telegram_web_app_url=os.getenv("TELEGRAM_WEB_APP_URL") or None,
        telegram_bot_poll_timeout_seconds=int(os.getenv("TELEGRAM_BOT_POLL_TIMEOUT_SECONDS", "30")),
        telegram_media_group_flush_seconds=float(
            os.getenv("TELEGRAM_MEDIA_GROUP_FLUSH_SECONDS", "1.2")
        ),
        log_level=os.getenv("LOG_LEVEL", "INFO"),
    )


def _required_env(name: str) -> str:
    value = os.getenv(name)
    if value is None or not value.strip():
        raise RuntimeError(f"{name} is required for telegram-bot service.")
    return value
