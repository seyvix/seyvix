from pathlib import Path

import pytest
from pydantic import ValidationError

from app.core.config import Settings, _settings_env_files

STRONG_SECRET = "f3a9c1d2e4b5a6978877665544332211aabbccddeeff00112233445566778899"


def make_settings(**overrides: object) -> Settings:
    overrides.setdefault("telegram_dev_login_enabled", False)
    return Settings(_env_file=None, **overrides)  # type: ignore[call-arg]


def test_settings_env_files_are_absolute_and_cwd_independent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("SEYVIX_IGNORE_ENV_FILES", raising=False)
    config_file = tmp_path / "repo" / "backend" / "app" / "core" / "config.py"
    config_file.parent.mkdir(parents=True)
    config_file.touch()

    assert _settings_env_files(config_file) == (
        tmp_path / "repo" / ".env",
        tmp_path / "repo" / "backend" / ".env",
    )


def test_list_settings_accept_csv_and_json(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ADMIN_TELEGRAM_IDS", " 1, 22 ,333 ")
    monkeypatch.setenv("CORS_ALLOWED_ORIGINS", '["https://a.example","https://b.example"]')

    settings = make_settings()

    assert settings.admin_telegram_ids == [1, 22, 333]
    assert settings.cors_allowed_origins == ["https://a.example", "https://b.example"]


@pytest.mark.parametrize(("raw", "expected"), [("local", "development"), ("prod", "production")])
def test_app_env_aliases(raw: str, expected: str) -> None:
    settings = make_settings(
        app_env=raw,
        auth_jwt_secret=STRONG_SECRET,
        postgres_password="pw-not-default",
        admin_telegram_ids=[1],
    )

    assert settings.app_env == expected


def test_derived_public_url_properties() -> None:
    settings = make_settings(public_url="https://notes.example.com/")

    assert settings.refresh_cookie_secure is True
    assert settings.telegram_login_redirect_url == "https://notes.example.com/auth/callback"
    assert settings.telegram_web_app_url == "https://notes.example.com"
    assert make_settings(public_url="http://localhost:8080").refresh_cookie_secure is False


def test_ai_is_enabled_only_with_api_key() -> None:
    assert make_settings(ai_api_key=None).ai_enabled is False
    assert make_settings(ai_api_key="sk-test").ai_enabled is True


def test_production_rejects_insecure_defaults() -> None:
    with pytest.raises(ValidationError) as error:
        make_settings(
            app_env="production",
            access_mode="allowlist",
            auth_jwt_secret="",
            postgres_password="postgres",
            telegram_dev_login_enabled=True,
        )

    message = str(error.value)
    assert "AUTH_JWT_SECRET" in message
    assert "POSTGRES_PASSWORD" in message
    assert "TELEGRAM_DEV_LOGIN_ENABLED" in message
    assert "ADMIN_TELEGRAM_IDS" in message


def test_production_requires_strong_internal_token_when_bot_enabled() -> None:
    base = {
        "app_env": "production",
        "auth_jwt_secret": STRONG_SECRET,
        "postgres_password": "pw-not-default",
        "admin_telegram_ids": [1],
        "telegram_bot_token": "123:abc",
    }
    with pytest.raises(ValidationError, match="TELEGRAM_INTERNAL_TOKEN"):
        make_settings(**base, telegram_internal_token="short")

    assert make_settings(**base, telegram_internal_token=STRONG_SECRET).is_production


def test_open_access_mode_needs_no_admins_in_production() -> None:
    settings = make_settings(
        app_env="production",
        auth_jwt_secret=STRONG_SECRET,
        postgres_password="pw-not-default",
        access_mode="open",
    )

    assert settings.admin_telegram_ids == []
