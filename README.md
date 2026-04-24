# VKR API

## Быстрый запуск

1. Создать `.env` по примеру из `.env.example`.

```bash
cp .env.example .env
```

2. Поднять локальную инфраструктуру:

```bash
docker compose up -d postgres redis
```

3. Запустить API локально:

```bash
uv sync
uv run uvicorn app.main:app --reload
```

4. Либо запустить всё в контейнерах:

```bash
docker compose up --build
```

5. Для dev-режима в контейнере с автоперезагрузкой:

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml up --build
```

6. Прогнать проверки:

```bash
uv run pytest
uv run ruff check app tests
uv run mypy app
```

## Ручки сейчас

- `GET /api/v1/health`
- `GET /api/v1/modules`
- `POST /api/v1/auth/register`
- `POST /api/v1/auth/login`
- `POST /api/v1/auth/refresh`
- `POST /api/v1/auth/logout`
- `GET /api/v1/auth/me`

## Задачи

### надо

- [ ] Добавить password policy и валидацию входных данных для auth
- [ ] Добавить rate limiting на `register/login/refresh`
- [ ] Добавить интеграционные auth-тесты на PostgreSQL

### Модули

- [ ] `content`
  Хранение единиц контента, metadata, версий и базовых операций чтения/записи
- [ ] `snapshots`
  Создание и хранение снапшотов контента и связанных состояний
- [ ] `vectorization`
  Чанкинг, постановка задач на embeddings и синхронизация векторного индекса
- [ ] `search`
  Поиск, фильтрация, ранжирование и единый query API
- [ ] `llm`
  Провайдеры LLM, execution layer, промпты и orchestration
- [ ] `plugins`
  Подключаемые расширения и SDK для внешних модулей

### когда-то позже

- [ ] Добавить наблюдаемость: structured logs, metrics, health/readiness checks
- [ ] Ввести фоновые задачи и job processing для тяжёлых операций
- [ ] Подготовить базовые контракты между модулями и правила расширения
