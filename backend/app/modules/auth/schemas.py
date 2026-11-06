from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, computed_field, field_validator, model_validator

from app.core.config import get_settings
from app.modules.auth.security import normalize_telegram_username


class TelegramLoginRequest(BaseModel):
    # extra="allow" so tgAuthResult JSON extra fields are preserved for hash verification
    model_config = ConfigDict(extra="allow")
    id: int = Field(
        gt=0,
        examples=[100500],
        description="Telegram user id returned by the Login Widget.",
    )
    first_name: str = Field(
        min_length=1,
        max_length=255,
        examples=["Telegram"],
        description="Telegram first name returned by the Login Widget.",
    )
    last_name: str | None = Field(
        default=None,
        max_length=255,
        examples=["User"],
        description="Telegram last name returned by the Login Widget.",
    )
    username: str | None = Field(
        default=None,
        max_length=255,
        examples=["telegram_user"],
        description="Telegram username returned by the Login Widget.",
    )
    photo_url: str | None = Field(
        default=None,
        max_length=2048,
        examples=["https://t.me/i/userpic/320/example.jpg"],
        description="Telegram profile photo URL returned by the Login Widget.",
    )
    auth_date: int = Field(
        gt=0,
        examples=[1713950000],
        description="Unix timestamp returned by the Login Widget.",
    )
    hash: str = Field(
        examples=["0123456789abcdef"],
        description="Telegram Login Widget integrity hash.",
    )


class TelegramAuthResultRequest(BaseModel):
    tg_auth_result: str = Field(
        min_length=1,
        description="base64url-encoded JSON auth result from oauth.telegram.org redirect.",
    )


class TelegramWebAppLoginRequest(BaseModel):
    init_data: str = Field(
        min_length=1,
        description="Raw Telegram.WebApp.initData query string from a Telegram Mini App.",
    )


class TelegramLoginCodeExchangeRequest(BaseModel):
    code: str = Field(
        min_length=1,
        examples=["opaque-login-code"],
        description="One-time login code received from the Telegram redirect callback.",
    )


class TelegramOidcCodeExchangeRequest(BaseModel):
    code: str = Field(
        min_length=1,
        description="Authorization code returned by Telegram OIDC.",
    )
    state: str = Field(
        min_length=1,
        description=(
            "State value returned by Telegram OIDC and matched against the httpOnly cookie."
        ),
    )


class UserResponse(BaseModel):
    id: str = Field(description="Unique user identifier.")
    telegram_id: str = Field(description="Telegram user identifier.")
    telegram_username: str | None = Field(description="Telegram username.")
    telegram_photo_url: str | None = Field(description="Telegram profile photo URL.")
    display_name: str = Field(description="Display name visible in the site UI.")
    is_active: bool = Field(description="Whether the account is active and allowed to sign in.")

    @computed_field  # type: ignore[prop-decorator]
    @property
    def is_admin(self) -> bool:
        try:
            return int(self.telegram_id) in get_settings().admin_telegram_ids
        except ValueError:
            return False

    @computed_field  # type: ignore[prop-decorator]
    @property
    def avatar_url(self) -> str | None:
        if not self.telegram_photo_url:
            return None
        return f"{get_settings().api_prefix}/auth/me/avatar"


class AuthTokensResponse(BaseModel):
    user: UserResponse = Field(description="Current authenticated user.")
    access_token: str = Field(description="Short-lived bearer token used in Authorization header.")
    token_type: str = Field(
        default="bearer",
        description="Authorization scheme for the access token.",
    )


class AuthSessionResponse(BaseModel):
    id: str = Field(description="Unique session identifier.")
    created_at: str = Field(description="Session creation timestamp in ISO 8601.")
    last_used_at: str | None = Field(description="Last usage timestamp in ISO 8601.")
    expires_at: str = Field(description="Session expiration timestamp in ISO 8601.")
    user_agent: str | None = Field(description="Captured user-agent for the session.")
    ip_address: str | None = Field(description="Captured client IP address for the session.")
    is_current: bool = Field(
        description="Whether this is the current session for the bearer token."
    )


class AccessGrantResponse(BaseModel):
    id: str
    telegram_user_id: int | None
    username: str | None
    note: str | None
    created_at: datetime
    last_login_at: datetime | None
    display_name: str | None = Field(
        default=None,
        description="Display name of the Seyvix user bound to this grant, if they signed in.",
    )


class AccessListResponse(BaseModel):
    mode: Literal["allowlist", "open"]
    admins: list[int]
    items: list[AccessGrantResponse]


class AccessGrantCreateRequest(BaseModel):
    telegram_user_id: int | None = Field(default=None, gt=0)
    username: str | None = Field(default=None, max_length=64, description="With or without @.")
    note: str | None = Field(default=None, max_length=500)

    @field_validator("username")
    @classmethod
    def normalize_username(cls, value: str | None) -> str | None:
        return normalize_telegram_username(value)

    @model_validator(mode="after")
    def require_identity(self) -> "AccessGrantCreateRequest":
        if self.telegram_user_id is None and self.username is None:
            raise ValueError("Either telegram_user_id or username is required.")
        return self
