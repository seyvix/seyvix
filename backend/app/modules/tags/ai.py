"""AI gating and request-path AI calls shared by the tags and taxonomy modules."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable
from typing import TypeVar

from fastapi import status

from app.api.errors import AppError
from app.core.config import Settings
from app.core.logging import get_logger
from app.modules.llm.client import AIResponseError, AIUnavailableError

logger = get_logger(__name__)

T = TypeVar("T")

# A user is waiting on these calls; they must fail fast with a clear message rather than
# hold a worker slot for the AI client's full retry budget.
INTERACTIVE_AI_TIMEOUT_SECONDS = 45.0


def tagging_enabled(settings: Settings) -> bool:
    return settings.ai_enabled and settings.ai_tags_enabled


def taxonomy_ai_enabled(settings: Settings) -> bool:
    return settings.ai_enabled and settings.ai_taxonomy_enabled


def ai_disabled_error(message: str) -> AppError:
    return AppError(status_code=status.HTTP_409_CONFLICT, code="ai_disabled", message=message)


async def interactive_ai[T](call: Awaitable[T], *, operation: str) -> T:
    """Await an AI call on a request path with a tight deadline and user-facing errors.

    Callers must not hold a database transaction open while awaiting (commit first).
    """
    try:
        async with asyncio.timeout(INTERACTIVE_AI_TIMEOUT_SECONDS):
            return await call
    except TimeoutError as exc:
        logger.warning("ai.interactive.timeout", operation=operation)
        raise AppError(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            code="ai_unavailable",
            message="The AI service did not answer in time. Please try again later.",
        ) from exc
    except AIUnavailableError as exc:
        logger.warning("ai.interactive.unavailable", operation=operation, error=str(exc))
        raise AppError(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            code="ai_unavailable",
            message="The AI service is unavailable right now. Please try again later.",
        ) from exc
    except AIResponseError as exc:
        logger.warning("ai.interactive.bad_response", operation=operation, error=str(exc))
        raise AppError(
            status_code=status.HTTP_502_BAD_GATEWAY,
            code="ai_bad_response",
            message="The AI service returned an unusable answer. Please try again.",
        ) from exc
