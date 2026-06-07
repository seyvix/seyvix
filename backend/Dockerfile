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
        ffmpeg \
        fontconfig \
        fonts-dejavu \
        fonts-liberation \
        libreoffice \
    && rm -rf /var/lib/apt/lists/*

# Install Playwright Chromium and its OS dependencies
RUN pip install playwright && playwright install --with-deps chromium

FROM base AS production-deps

COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

FROM production-deps AS production

COPY backend/ ./

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

FROM base AS development

COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --frozen --no-install-project

COPY backend/ ./

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]
