FROM python:3.13-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH="/opt/venv/bin:$PATH"

WORKDIR /app

COPY --from=ghcr.io/astral-sh/uv:0.8.13 /uv /bin/uv

FROM base AS production-deps

COPY telegram-bot/pyproject.toml ./
RUN uv sync --no-dev --no-install-project

FROM production-deps AS production

COPY telegram-bot/ ./

CMD ["python", "-m", "telegram_bot.main"]

FROM base AS development

COPY telegram-bot/pyproject.toml ./
RUN uv sync --no-install-project

COPY telegram-bot/ ./

CMD ["python", "-m", "telegram_bot.main"]
