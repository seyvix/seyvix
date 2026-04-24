from pydantic import BaseModel, Field


class TelegramLoginRequest(BaseModel):
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


class TelegramLoginCodeExchangeRequest(BaseModel):
    code: str = Field(
        min_length=1,
        examples=["opaque-login-code"],
        description="One-time login code received from the Telegram redirect callback.",
    )


class UserResponse(BaseModel):
    id: str = Field(description="Unique user identifier.")
    telegram_id: str = Field(description="Telegram user identifier.")
    telegram_username: str | None = Field(description="Telegram username.")
    telegram_photo_url: str | None = Field(description="Telegram profile photo URL.")
    display_name: str = Field(description="Display name visible in the site UI.")
    is_active: bool = Field(description="Whether the account is active and allowed to sign in.")


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
