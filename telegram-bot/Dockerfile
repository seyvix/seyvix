# Build context: repository root (see /.dockerignore).

ARG PYTHON_IMAGE=python:3.13-slim-trixie
ARG UV_IMAGE=ghcr.io/astral-sh/uv:0.8.24

FROM ${UV_IMAGE} AS uv

FROM ${PYTHON_IMAGE} AS deps
COPY --from=uv /uv /usr/local/bin/uv
ENV UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never
WORKDIR /app
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=telegram-bot/pyproject.toml,target=pyproject.toml \
    --mount=type=bind,source=telegram-bot/uv.lock,target=uv.lock \
    uv sync --frozen --no-dev --no-install-project

FROM ${PYTHON_IMAGE} AS bot
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    VIRTUAL_ENV=/opt/venv \
    PATH="/opt/venv/bin:$PATH"
RUN groupadd --system --gid 10001 seyvix \
    && useradd --system --uid 10001 --gid seyvix --no-create-home seyvix
WORKDIR /app
COPY --from=deps /opt/venv /opt/venv
COPY telegram-bot/telegram_bot ./telegram_bot
RUN python -m compileall -q telegram_bot
USER seyvix
CMD ["python", "-m", "telegram_bot.main"]
