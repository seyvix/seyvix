import os
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal, Self

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict
from sqlalchemy import URL

INSECURE_SECRET_MARKERS = ("change-me", "changeme", "secret", "password")
MIN_SECRET_LENGTH = 32


def _settings_env_files(config_file: Path = Path(__file__)) -> tuple[Path, ...]:
    """Local `.env` files; `SEYVIX_IGNORE_ENV_FILES=1` disables them (tests, CI)."""
    if os.environ.get("SEYVIX_IGNORE_ENV_FILES") == "1":
        return ()
    backend_root = config_file.resolve().parents[2]
    project_root = backend_root.parent
    return project_root / ".env", backend_root / ".env"


def _is_weak_secret(value: str | None) -> bool:
    if not value or len(value) < MIN_SECRET_LENGTH:
        return True
    lowered = value.casefold()
    return any(marker in lowered for marker in INSECURE_SECRET_MARKERS)


class Settings(BaseSettings):
    """Runtime configuration.

    Only the values documented in `.env.example` are meant to be tuned per deployment;
    the rest are sane internal defaults kept here so they stay discoverable and testable.
    """

    # --- Application -------------------------------------------------------------------
    app_name: str = "Seyvix"
    app_version: str = "1.0.0"
    app_env: Literal["development", "production"] = "development"
    api_prefix: str = "/api/v1"
    log_level: str = "INFO"
    # Public origin of the deployment, e.g. https://seyvix.example.com. Used for cookies,
    # Telegram login redirects and the Telegram Web App button.
    public_url: str = "http://localhost:8080"
    cors_allowed_origins: Annotated[list[str], NoDecode] = Field(default_factory=list)
    max_upload_bytes: int = 100 * 1024 * 1024

    # --- PostgreSQL ----------------------------------------------------------------------
    sqlalchemy_echo: bool = False
    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_db: str = "seyvix"
    postgres_user: str = "seyvix"
    postgres_password: str = "seyvix"
    db_pool_size: int = Field(default=5, ge=1)
    db_max_overflow: int = Field(default=5, ge=0)
    db_pool_timeout_seconds: float = 10.0
    db_statement_timeout_ms: int = Field(default=60_000, ge=0)

    # --- Storage -------------------------------------------------------------------------
    storage_backend: Literal["local", "s3"] = "local"
    # Local backend root. In containers this is a named volume shared by api and worker.
    content_storage_root: str = "data/content"
    s3_endpoint_url: str = "http://localhost:9000"
    s3_access_key: str = ""
    s3_secret_key: str = ""
    s3_bucket: str = "seyvix"
    s3_region: str = "us-east-1"

    # --- Auth ----------------------------------------------------------------------------
    auth_jwt_secret: str = "change-me-dev-only-secret-0123456789abcdef"
    auth_jwt_algorithm: Literal["HS256"] = "HS256"
    access_token_ttl_minutes: int = 15
    # Sliding inactivity window; each refresh extends it, capped by the absolute lifetime.
    refresh_token_ttl_days: int = 30
    refresh_token_absolute_ttl_days: int = 180
    refresh_cookie_name: str = "refresh_token"
    refresh_cookie_samesite: Literal["lax", "strict", "none"] = "lax"

    # --- Access control ------------------------------------------------------------------
    # allowlist: only admins and users granted access (by Telegram id or @username) can log
    # in or use the bot. open: anyone with a Telegram account can sign up.
    access_mode: Literal["allowlist", "open"] = "allowlist"
    admin_telegram_ids: Annotated[list[int], NoDecode] = Field(default_factory=list)

    # --- Telegram ------------------------------------------------------------------------
    telegram_bot_token: str | None = None
    telegram_bot_username: str | None = None
    telegram_api_base: str = "https://api.telegram.org"
    # Shared secret between telegram-bot and api. Required when the bot is enabled.
    telegram_internal_token: str | None = None
    telegram_login_max_age_seconds: int = 86400
    telegram_login_code_ttl_seconds: int = 60
    telegram_oidc_client_id: str | None = None
    telegram_oidc_client_secret: str | None = None
    telegram_oidc_proxy_url: str | None = None
    telegram_oidc_authorization_url: str = "https://oauth.telegram.org/auth"
    telegram_oidc_token_url: str = "https://oauth.telegram.org/token"
    telegram_oidc_jwks_url: str = "https://oauth.telegram.org/.well-known/jwks.json"
    telegram_oidc_issuer: str = "https://oauth.telegram.org"
    telegram_oidc_scope: str = "openid profile"
    telegram_dev_login_enabled: bool = False
    telegram_dev_user_id: int = 777001
    telegram_dev_first_name: str = "Local"
    telegram_dev_last_name: str | None = "Tester"
    telegram_dev_username: str | None = "local_tester"
    telegram_dev_photo_url: str | None = None

    # --- AI (any OpenAI-compatible API) --------------------------------------------------
    # AI features are enabled iff ai_api_key is set; without it the app works fully,
    # search falls back to full-text only and enrichment steps are skipped.
    ai_base_url: str = "https://api.openai.com/v1"
    ai_api_key: str | None = None
    ai_chat_model: str = "gpt-4o-mini"
    ai_vision_model: str = "gpt-4o-mini"
    ai_transcription_model: str = "whisper-1"
    ai_embedding_model: str = "text-embedding-3-small"
    # Providers with asymmetric embeddings (e.g. Yandex text-search-doc/-query) use a separate
    # model for search queries; defaults to ai_embedding_model.
    ai_embedding_query_model: str | None = None
    # Optional per-capability endpoints (e.g. chat on one provider, Whisper on another);
    # each falls back to ai_base_url / ai_api_key.
    ai_embedding_base_url: str | None = None
    ai_embedding_api_key: str | None = None
    ai_vision_base_url: str | None = None
    ai_vision_api_key: str | None = None
    ai_transcription_base_url: str | None = None
    ai_transcription_api_key: str | None = None
    # Baked into the database schema (pgvector column). Choose before the first start;
    # changing it later requires a migration and full re-index.
    ai_embedding_dimensions: int = Field(default=1024, ge=64, le=4000)
    ai_embedding_send_dimensions: bool = True
    ai_embedding_batch_size: int = Field(default=64, ge=1)
    ai_timeout_seconds: float = 60.0
    ai_max_retries: int = Field(default=3, ge=0)
    ai_max_concurrency: int = Field(default=4, ge=1)
    ai_tags_enabled: bool = True
    ai_taxonomy_enabled: bool = True
    ai_ocr_enabled: bool = True
    ai_vision_enabled: bool = False
    ai_transcription_enabled: bool = False
    ai_query_expansion_enabled: bool = False

    # --- Tags / taxonomy tuning ----------------------------------------------------------
    tags_max_per_note: int = 8
    tags_auto_apply_threshold: float = 0.85
    tags_suggest_threshold: float = 0.60
    tags_create_missing: bool = True
    taxonomy_classification_high_threshold: float = 0.80
    taxonomy_classification_medium_threshold: float = 0.60
    taxonomy_llm_accept_threshold: float = 0.80
    taxonomy_llm_propose_threshold: float = 0.60

    # --- Vectorization / search tuning ---------------------------------------------------
    vector_chunk_max_tokens: int = 384
    vector_chunk_overlap_tokens: int = 48
    vector_chunk_max_document_chars: int = 100_000
    vector_chunk_max_chunks_per_document: int = 200
    vector_chunk_config_version: str = "v2"
    # Baked into the generated tsvector column; changing it requires a migration.
    search_fts_config: str = Field(default="simple", pattern=r"^[a-z_]+$")
    search_rrf_k: int = 60
    search_hybrid_candidate_multiplier: int = 5
    search_query_expansion_max_queries: int = 3
    # Request-path AI budget (query embedding / expansion); on timeout search uses FTS only.
    search_ai_timeout_seconds: float = 4.0
    # Owners with at most this many embedded chunks get exact (100% recall) vector search;
    # larger owners use the HNSW index with iterative scan.
    search_vector_exact_max_chunks: int = 20_000
    search_hnsw_ef_search: int = 100
    # Cosine similarity below which a vector hit is treated as noise.
    search_semantic_min_score: float = 0.2
    vector_job_batch_size: int = Field(default=16, ge=1)

    # --- Snapshots -----------------------------------------------------------------------
    snapshot_screenshot_enabled: bool = True
    snapshot_page_pdf_enabled: bool = True
    snapshot_webpage_html_enabled: bool = False
    snapshot_office_conversion_enabled: bool = True
    snapshot_office_converter_command: str = "soffice"
    snapshot_office_converter_timeout_seconds: int = 90
    snapshot_timeout_seconds: int = 120
    snapshot_max_pdf_pages: int = 100
    snapshot_max_media_seconds: int = 1800
    snapshot_max_image_bytes: int = 10_000_000
    snapshot_vision_max_video_seconds: int = 300
    snapshot_vision_video_frame_interval_seconds: int = 15
    snapshot_vision_max_frames_per_request: int = 4
    snapshot_transcription_chunk_seconds: int = 600
    # Headless Chromium is started lazily and shut down after this much idle time.
    snapshot_browser_idle_seconds: int = 120

    # --- Worker --------------------------------------------------------------------------
    worker_idle_poll_seconds: float = 10.0
    worker_job_lease_seconds: int = 900
    worker_max_job_attempts: int = 5
    worker_snapshot_concurrency: int = Field(default=1, ge=1)
    worker_ai_concurrency: int = Field(default=2, ge=1)
    outbox_batch_size: int = 100
    outbox_max_attempts: int = 10
    outbox_retention_days: int = 7
    trash_retention_days: int = 30
    maintenance_interval_seconds: int = 3600

    model_config = SettingsConfigDict(
        env_file=_settings_env_files(),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @field_validator("app_env", mode="before")
    @classmethod
    def normalize_env(cls, value: object) -> object:
        if isinstance(value, str) and value.strip().casefold() in {"local", "dev", "test"}:
            return "development"
        if isinstance(value, str) and value.strip().casefold() in {"prod"}:
            return "production"
        return value

    @field_validator("cors_allowed_origins", "admin_telegram_ids", mode="before")
    @classmethod
    def split_csv(cls, value: object) -> object:
        """Accept `a,b,c` or a JSON list for list-valued env vars."""
        if isinstance(value, str):
            stripped = value.strip()
            if stripped.startswith("["):
                import json

                return json.loads(stripped)
            return [item.strip() for item in stripped.split(",") if item.strip()]
        return value

    @model_validator(mode="after")
    def validate_production(self) -> Self:
        if self.app_env != "production":
            return self
        problems: list[str] = []
        if _is_weak_secret(self.auth_jwt_secret):
            problems.append(f"AUTH_JWT_SECRET must be a random string of >= {MIN_SECRET_LENGTH}")
        if self.postgres_password in {"", "postgres", "seyvix"}:
            problems.append("POSTGRES_PASSWORD must be set to a non-default value")
        if self.telegram_dev_login_enabled:
            problems.append("TELEGRAM_DEV_LOGIN_ENABLED must be false in production")
        if self.telegram_bot_token and _is_weak_secret(self.telegram_internal_token):
            problems.append(
                f"TELEGRAM_INTERNAL_TOKEN must be a random string of >= {MIN_SECRET_LENGTH}"
            )
        if self.access_mode == "allowlist" and not self.admin_telegram_ids:
            problems.append("ADMIN_TELEGRAM_IDS must list at least one id in allowlist mode")
        if self.storage_backend == "s3" and not (self.s3_access_key and self.s3_secret_key):
            problems.append("S3_ACCESS_KEY and S3_SECRET_KEY are required for STORAGE_BACKEND=s3")
        if problems:
            raise ValueError("Invalid production configuration: " + "; ".join(problems))
        return self

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

    @property
    def ai_enabled(self) -> bool:
        return bool(self.ai_api_key)

    @property
    def public_origin(self) -> str:
        return self.public_url.rstrip("/")

    @property
    def refresh_cookie_secure(self) -> bool:
        return self.public_origin.startswith("https://")

    @property
    def telegram_login_redirect_url(self) -> str:
        return f"{self.public_origin}/auth/callback"

    @property
    def telegram_web_app_url(self) -> str:
        return self.public_origin

    @property
    def sqlalchemy_database_uri(self) -> str:
        return URL.create(
            drivername="postgresql+asyncpg",
            username=self.postgres_user,
            password=self.postgres_password,
            host=self.postgres_host,
            port=self.postgres_port,
            database=self.postgres_db,
        ).render_as_string(hide_password=False)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
