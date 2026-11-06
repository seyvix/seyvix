from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.cache import install_cache_control
from app.api.errors import install_error_handlers
from app.api.router import api_router
from app.core.config import Settings, get_settings
from app.core.database import build_engine, build_session_factory_from_engine
from app.core.logging import configure_logging, get_logger
from app.models import import_all_models
from app.modules.llm.client import close_ai_client
from app.platform.storage.factory import build_storage_backend


def configure_cors(app: FastAPI, settings: Settings) -> None:
    # Same-origin by default (Caddy serves web + /api); CORS only for extra origins.
    if not settings.cors_allowed_origins:
        return
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_allowed_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    logger = get_logger(__name__)
    engine = None
    # Tests may inject their own session factory before startup.
    if getattr(app.state, "session_factory", None) is None:
        engine = build_engine(settings, application_name="api")
        app.state.session_factory = build_session_factory_from_engine(engine)
    logger.info("api.starting", version=settings.app_version, env=settings.app_env)
    try:
        yield
    finally:
        await close_ai_client()
        if engine is not None:
            await engine.dispose()
            app.state.session_factory = None
        logger.info("api.stopped")


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level)
    import_all_models()
    docs_enabled = not settings.is_production
    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        docs_url=f"{settings.api_prefix}/docs" if docs_enabled else None,
        redoc_url=None,
        openapi_url=f"{settings.api_prefix}/openapi.json" if docs_enabled else None,
        lifespan=lifespan,
    )
    app.state.storage = build_storage_backend(settings)
    configure_cors(app, settings)
    install_cache_control(app, api_prefix=settings.api_prefix)
    install_error_handlers(app)
    app.include_router(api_router, prefix=settings.api_prefix)
    return app


app = create_app()
