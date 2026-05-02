# Seyvix

Seyvix - монорепозиторий с FastAPI backend в `api/` и Vite/React frontend в
`web/`. Docker и Compose управляются из корня репозитория.

## Структура

- `api/` - backend, workers, migrations, tests.
- `web/` - frontend-приложение.
- `docker/nginx/` - шаблон reverse proxy.
- `docker-compose.yml` - production-like стек.
- `docker-compose.dev.yml` - dev override с reload и прямыми портами.
- `.env.example` - единый шаблон окружения для всего продукта.

## Окружение

Создай один общий `.env` в корне репозитория:

```bash
cp .env.example .env
```

Для локальной разработки дефолты уже подходят. Перед деплоем на сервер обязательно
поменяй как минимум:

- `AUTH_JWT_SECRET`
- `POSTGRES_PASSWORD`
- `S3_SECRET_KEY`
- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_LOGIN_REDIRECT_URL`
- `CORS_ALLOWED_ORIGINS`
- `APP_SERVER_NAME`, `WEB_SERVER_NAME`, `API_SERVER_NAME`, если используются реальные домены

Для Docker Compose не нужны отдельные `api/.env` или `web/.env`.

## Разработка

Запуск полного dev-стека:

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml up --build
```

Дефолтные адреса:

- приложение через один порт: `http://localhost:8080`
- backend через proxy: `http://localhost:8080/api/v1/health`
- frontend напрямую через Vite: `http://localhost:5173`
- backend напрямую: `http://localhost:8000/api/v1/health`
- MinIO console: `http://localhost:9001`
- RabbitMQ management: `http://localhost:15672`

Dev override монтирует `api/` и `web/` внутрь контейнеров. Backend запускается с
Uvicorn reload, frontend - с Vite HMR.

Остановить стек:

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml down
```

Сбросить локальные Docker-данные:

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml down -v
```

## Деплой

На сервере настрой `.env`, затем запусти:

```bash
docker compose up -d --build
```

Production Compose наружу публикует только `proxy` на `APP_PORT`. PostgreSQL,
Redis, RabbitMQ, MinIO, API, frontend и workers остаются во внутренней Docker-сети.

Проверить состояние:

```bash
docker compose ps
docker compose logs -f proxy api web
```

Миграции backend при необходимости можно запустить вручную:

```bash
docker compose run --rm api alembic upgrade head
```

Сервис `api` также запускает миграции при старте.

## Маршрутизация

Дефолтный режим использует один внешний порт:

- `/api/*` -> FastAPI `api:8000`
- `/*` -> frontend `web`

Пример для одного домена:

```env
APP_PORT=8080
APP_SERVER_NAME=example.com
TELEGRAM_LOGIN_REDIRECT_URL=https://example.com/auth/telegram
CORS_ALLOWED_ORIGINS=["https://example.com"]
```

Тот же proxy поддерживает отдельные домены на том же внешнем порту:

```env
APP_SERVER_NAME=example.com
WEB_SERVER_NAME=app.example.com
API_SERVER_NAME=api.example.com
TELEGRAM_LOGIN_REDIRECT_URL=https://app.example.com/auth/telegram
CORS_ALLOWED_ORIGINS=["https://example.com","https://app.example.com","https://api.example.com"]
```

В таком режиме:

- `https://example.com/api/*` и `https://api.example.com/*` идут в backend.
- `https://example.com/*` и `https://app.example.com/*` идут во frontend.

Для TLS поставь Caddy, Traefik, nginx или cloud load balancer перед этим Compose
стеком и прокинь трафик на `APP_PORT`.

## Проверки

Backend:

```bash
cd api
uv run pytest
uv run ruff check app tests
uv run mypy app
```

Frontend:

```bash
cd web
npm test
npm run build
```

Проверка Compose-конфигов:

```bash
docker compose config
docker compose -f docker-compose.yml -f docker-compose.dev.yml config
```
