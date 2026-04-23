from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.errors import install_error_handlers
from app.api.router import api_router
from app.core.config import Settings, get_settings
from app.core.database import build_session_factory
from app.core.lifespan import lifespan
from app.core.logging import configure_logging


def configure_cors(app: FastAPI, settings: Settings) -> None:
    if not settings.cors_allowed_origins and not settings.cors_allow_origin_regex:
        return

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_allowed_origins,
        allow_origin_regex=settings.cors_allow_origin_regex,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level)

    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        lifespan=lifespan,
    )
    app.state.session_factory = build_session_factory(
        settings.database_url,
        echo=settings.sqlalchemy_echo,
    )
    configure_cors(app, settings)
    install_error_handlers(app)
    app.include_router(api_router, prefix=settings.api_prefix)
    return app


app = create_app()
