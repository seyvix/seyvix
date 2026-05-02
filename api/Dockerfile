FROM python:3.13-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH="/opt/venv/bin:$PATH"

WORKDIR /app

COPY --from=ghcr.io/astral-sh/uv:0.8.13 /uv /bin/uv

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential \
        curl \
        fontconfig \
        fonts-dejavu \
        fonts-liberation \
        libreoffice \
    && rm -rf /var/lib/apt/lists/*

FROM base AS production-deps

COPY api/pyproject.toml api/uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

FROM production-deps AS production

COPY api/ ./

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

FROM base AS development

COPY api/pyproject.toml api/uv.lock ./
RUN uv sync --frozen --no-install-project

COPY api/ ./

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]
