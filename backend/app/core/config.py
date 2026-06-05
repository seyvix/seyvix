from functools import lru_cache
from typing import Literal
from urllib.parse import quote

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import URL


class Settings(BaseSettings):
    app_name: str = "VKR API"
    app_version: str = "0.1.0"
    api_prefix: str = "/api/v1"
    log_level: str = "INFO"
    sqlalchemy_echo: bool = False
    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_db: str = "vkr_api"
    postgres_user: str = "postgres"
    postgres_password: str = "postgres"
    redis_host: str = "localhost"
    redis_port: int = 6379
    redis_db: int = 0
    redis_password: str | None = None
    rabbitmq_url: str = "amqp://guest:guest@localhost:5672/"
    rabbitmq_exchange: str = "app.events"
    rabbitmq_snapshot_queue: str = "snapshot-worker.events"
    rabbitmq_snapshot_retry_queue: str = "snapshot-worker.events.retry"
    rabbitmq_snapshot_dlq: str = "snapshot-worker.events.dlq"
    rabbitmq_vectorization_queue: str = "vectorization-worker.events"
    rabbitmq_vectorization_retry_queue: str = "vectorization-worker.events.retry"
    rabbitmq_vectorization_dlq: str = "vectorization-worker.events.dlq"
    rabbitmq_taxonomy_queue: str = "taxonomy-worker.events"
    rabbitmq_taxonomy_retry_queue: str = "taxonomy-worker.events.retry"
    rabbitmq_taxonomy_dlq: str = "taxonomy-worker.events.dlq"
    rabbitmq_tags_queue: str = "tags-worker.events"
    rabbitmq_tags_retry_queue: str = "tags-worker.events.retry"
    rabbitmq_tags_dlq: str = "tags-worker.events.dlq"
    rabbitmq_retry_ttl_ms: int = 30000
    outbox_publisher_batch_size: int = 50
    outbox_publisher_poll_interval_seconds: int = 2
    storage_backend: Literal["local", "s3"] = "local"
    s3_endpoint_url: str = "http://localhost:9000"
    s3_public_endpoint_url: str = "http://localhost:9000"
    s3_access_key: str = "minio"
    s3_secret_key: str = "minio-password"
    s3_bucket: str = "app-storage"
    s3_region: str = "us-east-1"
    s3_force_path_style: bool = True
    auth_jwt_secret: str = "change-me-for-production-32-bytes"
    auth_jwt_algorithm: str = "HS256"
    access_token_ttl_minutes: int = 15
    refresh_token_ttl_days: int = 30
    refresh_cookie_name: str = "refresh_token"
    refresh_cookie_secure: bool = False
    refresh_cookie_samesite: Literal["lax", "strict", "none"] = "lax"
    telegram_bot_token: str | None = None
    telegram_internal_token: str | None = None
    telegram_default_group_window_seconds: int = 3
    telegram_login_max_age_seconds: int = 86400
    telegram_login_redirect_url: str | None = None
    telegram_oidc_client_id: str | None = None
    telegram_oidc_client_secret: str | None = None
    telegram_oidc_proxy_url: str | None = None
    telegram_oidc_authorization_url: str = "https://oauth.telegram.org/auth"
    telegram_oidc_token_url: str = "https://oauth.telegram.org/token"
    telegram_oidc_jwks_url: str = "https://oauth.telegram.org/.well-known/jwks.json"
    telegram_oidc_issuer: str = "https://oauth.telegram.org"
    telegram_oidc_audience: str | None = None
    telegram_oidc_scope: str = "openid profile"
    telegram_login_code_ttl_seconds: int = 60
    telegram_dev_login_enabled: bool = False
    telegram_dev_user_id: int = 100500
    telegram_dev_first_name: str = "Dev"
    telegram_dev_last_name: str | None = "User"
    telegram_dev_username: str | None = "dev_user"
    telegram_dev_photo_url: str | None = None
    content_storage_root: str = "data/content"
    snapshot_archive_screenshot_enabled: bool = True
    snapshot_archive_webpage_html_enabled: bool = False
    snapshot_archive_pdf_enabled: bool = True
    snapshot_archive_markdown_enabled: bool = True
    snapshot_archive_org_enabled: bool = False
    snapshot_worker_batch_size: int = 10
    snapshot_worker_poll_interval_seconds: int = 10
    snapshot_ocr_provider: Literal["disabled", "local", "http", "openai_compatible"] = "disabled"
    snapshot_ocr_http_url: str | None = None
    snapshot_ocr_languages: str = "eng+rus"
    snapshot_ocr_openai_base_url: str | None = None
    snapshot_ocr_openai_api_key: str | None = None
    snapshot_ocr_openai_model: str = "gpt-4o-mini"
    snapshot_ocr_max_image_bytes: int = 10_000_000
    snapshot_stt_provider: Literal["disabled", "local", "http", "openai_compatible"] = "disabled"
    snapshot_stt_http_url: str | None = None
    snapshot_stt_model: str = "base"
    snapshot_stt_openai_base_url: str | None = None
    snapshot_stt_openai_api_key: str | None = None
    snapshot_stt_openai_model: str = "whisper-1"
    snapshot_stt_chunk_seconds: int = 600
    snapshot_vision_provider: Literal["disabled", "http", "openai_compatible"] = "disabled"
    snapshot_vision_http_url: str | None = None
    snapshot_vision_openai_base_url: str | None = None
    snapshot_vision_openai_api_key: str | None = None
    snapshot_vision_openai_model: str = "gpt-4o-mini"
    snapshot_vision_max_video_seconds: int = 300
    snapshot_vision_max_image_bytes: int = 10_000_000
    snapshot_vision_video_chunk_seconds: int = 60
    snapshot_vision_video_frame_interval_seconds: int = 15
    snapshot_vision_max_frames_per_request: int = 4
    snapshot_extraction_timeout_seconds: int = 120
    snapshot_extraction_max_pdf_pages: int = 100
    snapshot_extraction_max_media_seconds: int = 1800
    vector_embedding_provider: Literal["fake", "http", "ollama", "yandex"] = "fake"
    vector_embedding_base_url: str | None = None
    vector_embedding_api_key: str | None = None
    vector_embedding_model: str = "fake-embedding"
    vector_embedding_dimensions: int = 384
    vector_embedding_batch_size: int = 64
    vector_embedding_timeout_seconds: int = 30
    vector_chunk_default_max_tokens: int = 800
    vector_chunk_default_overlap_tokens: int = 100
    vector_chunk_max_document_chars: int = 200000
    vector_chunk_max_chunks_per_document: int = 300
    vector_chunk_config_version: str = "v1"
    vector_worker_batch_size: int = 10
    vector_worker_poll_interval_seconds: int = 10
    vector_worker_lock_timeout_seconds: int = 300
    search_fts_config: str = "simple"
    search_rrf_k: int = 60
    search_hybrid_candidate_multiplier: int = 5
    search_query_expansion_enabled: bool = False
    search_query_expansion_model: str = "qwen3:4b-thinking"
    search_query_expansion_max_queries: int = 3
    search_engine: Literal["postgres", "meilisearch"] = "postgres"
    search_meilisearch_url: str | None = None
    search_meilisearch_api_key: str | None = None
    search_meilisearch_index_uid: str = "content_chunks"
    search_meilisearch_embedder: str = "content"
    search_meilisearch_timeout_seconds: int = 5
    search_meilisearch_hybrid_semantic_ratio: float = 0.5
    taxonomy_classification_high_threshold: float = 0.80
    taxonomy_classification_medium_threshold: float = 0.60
    taxonomy_llm_classification_accept_threshold: float = 0.80
    taxonomy_llm_classification_propose_threshold: float = 0.60
    taxonomy_llm_classification_fallback_to_semantic: bool = True
    taxonomy_llm_classification_model: str = "qwen3:4b-thinking"
    taxonomy_llm_provider: Literal["disabled", "http", "ollama"] | None = None
    taxonomy_llm_base_url: str | None = None
    taxonomy_llm_api_key: str | None = None
    taxonomy_llm_timeout_seconds: int | None = None
    taxonomy_worker_batch_size: int = 10
    taxonomy_worker_poll_interval_seconds: int = 10
    taxonomy_worker_lock_timeout_seconds: int = 300
    tags_llm_enabled: bool = False
    tags_llm_model: str = "qwen3:4b-thinking"
    tags_llm_provider: Literal["disabled", "http", "ollama"] | None = None
    tags_llm_base_url: str | None = None
    tags_llm_api_key: str | None = None
    tags_llm_timeout_seconds: int | None = None
    tags_llm_max_tags: int = 8
    tags_llm_auto_apply_threshold: float = 0.85
    tags_llm_suggest_threshold: float = 0.60
    tags_llm_create_missing_tags: bool = True
    tags_llm_prompt_version: str = "content_tags_v1"
    tags_worker_batch_size: int = 10
    tags_worker_poll_interval_seconds: int = 10
    tags_worker_lock_timeout_seconds: int = 300
    llm_structured_provider: Literal["disabled", "http", "ollama"] = "disabled"
    llm_structured_base_url: str | None = None
    llm_structured_api_key: str | None = None
    llm_structured_timeout_seconds: int = 120
    snapshot_office_converter_command: str | None = "libreoffice"
    cors_allowed_origins: list[str] = Field(default_factory=list)
    cors_allow_origin_regex: str | None = None

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

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

    @property
    def redis_url(self) -> str:
        auth_part = ""
        if self.redis_password:
            auth_part = f":{quote(self.redis_password, safe='')}@"

        return f"redis://{auth_part}{self.redis_host}:{self.redis_port}/{self.redis_db}"

    @field_validator("snapshot_office_converter_command", mode="before")
    @classmethod
    def default_office_converter_command(cls, value: str | None) -> str:
        if value is None or not value.strip():
            return "libreoffice"
        return value


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
