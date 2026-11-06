# Build context: repository root (see /.dockerignore).
#
# Targets:
#   api               uvicorn API, light worker (vectorization/tags/taxonomy/maintenance), migrations
#   worker-snapshots  snapshot worker: + Chromium headless shell, LibreOffice (nogui), ffmpeg, fonts
#   dev               development: dev dependencies + snapshot tooling, code is bind-mounted

ARG PYTHON_IMAGE=python:3.13-slim-trixie
ARG UV_IMAGE=ghcr.io/astral-sh/uv:0.8.24

FROM ${UV_IMAGE} AS uv

# --- runtime base: interpreter + unprivileged user ---------------------------------------
FROM ${PYTHON_IMAGE} AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    VIRTUAL_ENV=/opt/venv \
    PATH="/opt/venv/bin:$PATH" \
    CONTENT_STORAGE_ROOT=/data/content
RUN groupadd --system --gid 10001 seyvix \
    && useradd --system --uid 10001 --gid seyvix --create-home --home-dir /home/seyvix seyvix \
    && mkdir -p /data/content \
    && chown seyvix:seyvix /data/content
WORKDIR /app

# --- python dependencies (no build toolchain: every dependency ships wheels) -------------
FROM ${PYTHON_IMAGE} AS uv-base
COPY --from=uv /uv /usr/local/bin/uv
ENV UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never
WORKDIR /app

FROM uv-base AS deps
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=backend/pyproject.toml,target=pyproject.toml \
    --mount=type=bind,source=backend/uv.lock,target=uv.lock \
    uv sync --frozen --no-dev --no-install-project

# The API and light worker never drive a browser: skip Playwright (~135 MB).
FROM uv-base AS deps-api
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=backend/pyproject.toml,target=pyproject.toml \
    --mount=type=bind,source=backend/uv.lock,target=uv.lock \
    uv sync --frozen --no-dev --no-install-project --no-install-package playwright

# --- api: API server, migrations, light worker modules ------------------------------------
FROM runtime AS api
COPY --from=deps-api /opt/venv /opt/venv
COPY backend/alembic.ini ./
COPY backend/migrations ./migrations
COPY backend/app ./app
RUN python -m compileall -q app migrations
USER seyvix
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", \
     "--proxy-headers", "--forwarded-allow-ips=*", \
     "--timeout-graceful-shutdown", "20", "--no-server-header"]

# --- system tooling for snapshots ----------------------------------------------------------
FROM runtime AS snapshot-tools
ENV PLAYWRIGHT_BROWSERS_PATH=/opt/ms-playwright
# - LibreOffice nogui (writer/calc/impress; no Java, no GUI toolkits)
# - ffmpeg/ffprobe for audio/video thumbnails and transcription chunks
# - fonts: Latin/Cyrillic (DejaVu, Liberation = MS-metric compatible), CJK, emoji
# - shared libraries of Chromium headless shell (Playwright's list minus xvfb/extra fonts)
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt/lists,sharing=locked \
    rm -f /etc/apt/apt.conf.d/docker-clean \
    && apt-get update \
    && apt-get install -y --no-install-recommends \
        libreoffice-writer-nogui \
        libreoffice-calc-nogui \
        libreoffice-impress-nogui \
        ffmpeg \
        fontconfig \
        fonts-dejavu-core \
        fonts-liberation \
        fonts-noto-color-emoji \
        fonts-wqy-zenhei \
        libasound2t64 libatk-bridge2.0-0t64 libatk1.0-0t64 libatspi2.0-0t64 libcairo2 \
        libcups2t64 libdbus-1-3 libdrm2 libgbm1 libglib2.0-0t64 libnspr4 libnss3 \
        libpango-1.0-0 libx11-6 libxcb1 libxcomposite1 libxdamage1 libxext6 libxfixes3 \
        libxkbcommon0 libxrandr2
RUN --mount=type=bind,from=deps,source=/opt/venv,target=/opt/venv \
    playwright install --only-shell chromium \
    && rm -rf /tmp/* \
    && ! ldd /opt/ms-playwright/chromium_headless_shell-*/chrome-*/headless_shell | grep "not found" \
    && command -v soffice ffmpeg ffprobe

# --- worker-snapshots ----------------------------------------------------------------------
FROM snapshot-tools AS worker-snapshots
COPY --from=deps /opt/venv /opt/venv
COPY backend/app ./app
RUN python -m compileall -q app
USER seyvix
CMD ["python", "-m", "app.worker", "snapshots"]

# --- dev: dev dependencies; ./backend is bind-mounted over /app ---------------------------
FROM snapshot-tools AS dev
COPY --from=uv /uv /usr/local/bin/uv
ENV UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=backend/pyproject.toml,target=pyproject.toml \
    --mount=type=bind,source=backend/uv.lock,target=uv.lock \
    uv sync --frozen --no-install-project
USER seyvix
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]
