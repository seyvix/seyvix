from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from app.core.config import get_settings
from app.core.logging import get_logger
from fastapi import FastAPI


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    logger = get_logger(__name__)
    logger.info("application.starting", app_name=settings.app_name, version=settings.app_version)
    yield
    logger.info("application.stopping", app_name=settings.app_name)
