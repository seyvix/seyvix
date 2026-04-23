from pydantic import BaseModel, EmailStr, Field


class RegisterRequest(BaseModel):
    email: EmailStr = Field(
        examples=["user@example.com"],
        description="Unique email used as the login identifier.",
    )
    display_name: str = Field(
        min_length=1,
        max_length=255,
        examples=["User"],
        description="Public display name shown in the site UI.",
    )
    password: str = Field(
        min_length=8,
        examples=["StrongPass123!"],
        description="Raw password provided during registration.",
    )


class LoginRequest(BaseModel):
    email: EmailStr = Field(
        examples=["user@example.com"],
        description="User email used for login.",
    )
    password: str = Field(
        min_length=8,
        examples=["StrongPass123!"],
        description="Raw password for the account.",
    )


class UserResponse(BaseModel):
    id: str = Field(description="Unique user identifier.")
    email: EmailStr = Field(description="User email.")
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
