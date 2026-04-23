from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "VKR API"
    app_version: str = "0.1.0"
    api_prefix: str = "/api/v1"
    log_level: str = "INFO"
    sqlalchemy_echo: bool = False
    auth_jwt_secret: str = "change-me-for-production-32-bytes"
    auth_jwt_algorithm: str = "HS256"
    access_token_ttl_minutes: int = 15
    refresh_token_ttl_days: int = 30
    refresh_cookie_name: str = "refresh_token"
    refresh_cookie_secure: bool = False
    refresh_cookie_samesite: Literal["lax", "strict", "none"] = "lax"
    cors_allowed_origins: list[str] = Field(default_factory=list)
    cors_allow_origin_regex: str | None = None
    database_url: str = Field(
        default="postgresql+asyncpg://postgres:postgres@localhost:5432/vkr_api"
    )
    redis_url: str = "redis://localhost:6379/0"

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
