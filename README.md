# VKR API

## Быстрый запуск

1. Установить зависимости:

```bash
uv sync
```

2. Заполнить `.env` по примеру из `.env.example`:

3. Запустить API:

```bash
uv run uvicorn app.main:app --reload
```

4. Прогнать проверки:

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

- [ ] Применить Alembic-миграции к реальной PostgreSQL базе, рассмотреть возможность использовать другие бд???? возможно
- [ ] Добавить `docker-compose` для локального PostgreSQL/Redis
- [ ] Добавить password policy и валидацию входных данных для auth
- [ ] Добавить rate limiting на `register/login/refresh`
- [ ] Добавить logout-all / session management для пользователя
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

- [ ] Нормализовать конфигурацию окружений и добавить `env`-документацию
- [ ] Добавить наблюдаемость: structured logs, metrics, health/readiness checks
- [ ] Ввести фоновые задачи и job processing для тяжёлых операций
- [ ] Подготовить базовые контракты между модулями и правила расширения
