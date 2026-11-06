from __future__ import annotations

import os
from dataclasses import dataclass

# Telegram Bot API refuses getFile for files above 20 MB (cloud API limit).
TELEGRAM_MAX_DOWNLOAD_BYTES = 20 * 1024 * 1024
MANUAL_COLLECTION_REMINDER_IDLE_SECONDS = 1800
REMINDER_POLL_SECONDS = 60
MEDIA_GROUP_FLUSH_SECONDS = 1.2
USER_STATUS_CACHE_SECONDS = 60.0
MAX_BUFFERED_MATERIALS = 20


@dataclass(frozen=True, slots=True)
class Settings:
    telegram_bot_token: str
    telegram_internal_token: str
    backend_url: str = "http://api:8000/api/v1"
    public_url: str | None = None
    telegram_api_base: str | None = None
    group_window_seconds: float = 3.0
    log_level: str = "INFO"

    @property
    def web_app_url(self) -> str | None:
        """Telegram only opens Web Apps over HTTPS."""
        if self.public_url and self.public_url.startswith("https://"):
            return self.public_url.rstrip("/")
        return None


def get_settings() -> Settings:
    # Compose passes unset optional variables as empty strings: treat "" as unset.
    return Settings(
        telegram_bot_token=_required_env("TELEGRAM_BOT_TOKEN"),
        telegram_internal_token=_required_env("TELEGRAM_INTERNAL_TOKEN"),
        backend_url=(_env("BACKEND_URL") or "http://api:8000/api/v1").rstrip("/"),
        public_url=_env("PUBLIC_URL"),
        telegram_api_base=_env("TELEGRAM_API_BASE"),
        group_window_seconds=float(_env("TELEGRAM_GROUP_WINDOW_SECONDS") or "3"),
        log_level=(_env("LOG_LEVEL") or "INFO").upper(),
    )


def _env(name: str) -> str | None:
    value = os.getenv(name)
    return value.strip() if value and value.strip() else None


def _required_env(name: str) -> str:
    value = _env(name)
    if value is None:
        raise RuntimeError(f"{name} is required for the telegram-bot service.")
    return value
