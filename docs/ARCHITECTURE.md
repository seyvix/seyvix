# Архитектура Seyvix

## Процессы

```
            ┌────────────── caddy (web image) ──────────────┐
браузер ──► │ статика SPA (build/client) · /api/* → api:8000 │ ◄── HTTPS (Let's Encrypt)
            └───────────────────────────────────────────────┘
telegram-bot ──HTTP (Bearer TELEGRAM_INTERNAL_TOKEN)──► api
api ─────────┐
worker ──────┼──► postgres (pgvector)  — единственная инфраструктура: данные, очереди, события
snapshot-worker ┘   storage volume /data/content (или S3) — файлы
```

| сервис | образ / команда | назначение |
|---|---|---|
| `caddy` | `web` | SPA, reverse proxy, автоматический HTTPS (`SITE_ADDRESS`) |
| `api` | `api`: `uvicorn app.main:app` | REST API `/api/v1`, без Chromium/LibreOffice |
| `migrate` | `api`: `alembic upgrade head` | one-shot; `api` и воркеры стартуют после его успеха |
| `worker` | `api`: `python -m app.worker vectorization tags taxonomy maintenance` | лёгкие фоновые модули |
| `snapshot-worker` | `worker-snapshots`: `python -m app.worker snapshots` | снимки: Chromium headless shell, LibreOffice, ffmpeg |
| `telegram-bot` | `telegram-bot` (профиль `telegram`) | приём заметок из Telegram; БД не трогает, только API |
| `postgres` | `pgvector/pgvector:0.8.7-pg16-bookworm` | всё состояние |

Любой модуль воркера запускается отдельно (`python -m app.worker <module>...` или `all`),
поэтому модули можно разнести по процессам/контейнерам без изменений кода. `maintenance` и
`vectorization` должны работать ровно в одном процессе.

## Backend (`backend/app`)

- `core/` — `config.py` (единственный `Settings`, переменные окружения = имена полей),
  `database.py` (один engine на процесс, ограниченный пул, `statement_timeout`), логирование.
- `api/` — корневой router, единый формат ошибок `{"error": {"code", "message", "details"}}`,
  health: `/health/live`, `/health/ready` (БД + хранилище).
- `modules/<name>/` — бизнес-модули: `auth` (Telegram login, сессии, allowlist),
  `content` (заметки, загрузки, корзина, лента изменений `/notes/changes`), `snapshots`
  (скриншоты/PDF/текст ссылок и документов), `vectorization` (чанки + эмбеддинги),
  `search` (FTS + pgvector, RRF), `tags`, `taxonomy`, `recommendations`,
  `telegram_integration` (внутренние эндпоинты бота), `llm` (общий AI-клиент).
  Модуль импортирует другие модули только через их `contracts.py`.
- `contracts/events/` — типизированные события и таблица маршрутизации `routing.py`.
- `platform/` — `jobs.py` (очереди задач), `events/` (outbox + потребители),
  `storage/` (локальный том или S3, потоковый API).
- `worker/` — супервизор фоновых модулей (`python -m app.worker`).
- `models.py` — `import_all_models()` для alembic, воркеров и тестов.

Хранилище: всё, что относится к заметке, лежит под `objects/{content_object_id}/`
(оригиналы — `assets/{asset_id}/original.<ext>`, артефакты снимков —
`assets/{asset_id}/snapshots/...`; окончательное удаление = удаление префикса),
незавершённые загрузки — под `uploads/{owner_user_id}/{upload_id}/`. Отдельной таблицы
объектов хранилища нет. Временные файлы — только во временных каталогах.

AI необязателен: без `AI_API_KEY` поиск только полнотекстовый, обогащение пропускается.

## Протокол событий и задач (plain SQL)

Протокол не зависит от Python: воркер на любом языке, умеющем Postgres, может обслуживать
очередь, соблюдая правила ниже.

### Таблицы

**`events`** — неизменяемый журнал доменных событий; пишется в транзакции продюсера.

| колонка | тип | смысл |
|---|---|---|
| `id` | varchar(36) PK | UUID события |
| `name` | varchar(128) | например `content.object.created` |
| `version` | int | версия схемы payload |
| `occurred_at`, `created_at` | timestamptz | |
| `correlation_id` | varchar(36) | сквозной id цепочки обработки |
| `user_id` | varchar(36) null | владелец |
| `entity_id` | varchar(36) | id сущности (обычно заметки) |
| `payload` | jsonb | маленький JSON; крупные данные не встраиваются, только ссылки/id |

**`event_deliveries`** — по строке на пару (событие, потребитель): независимая очередь
каждого потребителя. `UNIQUE (event_id, consumer)`, `event_id → events.id ON DELETE CASCADE`.

**Таблицы задач** модулей: `snapshot_jobs`, `vectorization_jobs`, `tagging_jobs`,
`taxonomy_classification_jobs` (+ собственные колонки модуля).

У `event_deliveries` и всех таблиц задач одинаковые служебные колонки:

| колонка | тип | смысл |
|---|---|---|
| `status` | varchar(16) | `pending` · `processing` · `succeeded` · `failed` · `cancelled` |
| `priority` | int (100) | больше — раньше |
| `attempts` / `max_attempts` | int (0 / 5) | счётчик попыток и лимит |
| `run_after` | timestamptz | не брать раньше этого момента (бэкофф) |
| `locked_at` / `locked_by` | timestamptz / varchar(128) | аренда (lease) и id воркера |
| `last_error` | text | последняя ошибка (до 4000 символов) |
| `created_at` / `updated_at` | timestamptz | |

Частичные индексы: `ix_<table>_claim (priority DESC, run_after) WHERE status='pending'` и
`ix_<table>_lease (locked_at) WHERE status='processing'`.

### Маршрутизация

Продюсер в своей транзакции вставляет строку в `events` и по строке в `event_deliveries`
на каждого потребителя из `app/contracts/events/routing.py`:

| событие | потребители |
|---|---|
| `content.object.created`, `content.object.updated` | `snapshots` |
| `content.object.deleted` | `vectorization` |
| `snapshot.text_representation.completed` | `vectorization`, `tags` |
| `content.tags.completed` | `taxonomy` |

Новый потребитель = новое имя очереди в таблице маршрутизации.

### Пробуждение: LISTEN/NOTIFY

Триггер на каждой таблице задач и на `event_deliveries` при INSERT/UPDATE строки в статус
`pending` выполняет `pg_notify('seyvix_jobs', TG_TABLE_NAME)` (payload — имя таблицы;
уведомление доставляется после COMMIT). Воркер держит одно соединение с
`LISTEN seyvix_jobs`, будит соответствующие циклы и **всё равно** опрашивает очередь раз в
`WORKER_IDLE_POLL_SECONDS` (NOTIFY — ускорение, не гарантия). После переподключения
LISTEN воркер один раз проверяет все очереди.

### Обработка доставки события (`event_deliveries`)

Обработчик события быстрый (обычно только ставит задачу модуля), поэтому выполняется в
одной короткой транзакции:

```sql
BEGIN;
SELECT d.*, e.* FROM event_deliveries d JOIN events e ON e.id = d.event_id
 WHERE d.consumer = $1 AND d.status = 'pending' AND d.run_after <= now()
 ORDER BY d.priority DESC, d.run_after
 LIMIT $2
 FOR UPDATE OF d SKIP LOCKED;
-- для каждой доставки, в SAVEPOINT: реакция модуля (идемпотентная!), затем
UPDATE event_deliveries SET status='succeeded', attempts=attempts+1, last_error=NULL,
       locked_at=NULL, locked_by=NULL, updated_at=now() WHERE id=$id;
-- при ошибке: ROLLBACK TO SAVEPOINT и бэкофф (см. ниже)
COMMIT;
```

### Обработка задачи (долгая работа)

Строки не блокируются во время работы — только аренда:

1. **Claim** (короткая транзакция, сразу COMMIT):
   ```sql
   UPDATE <jobs> SET status='processing', attempts=attempts+1,
          locked_at=now(), locked_by=$worker_id, updated_at=now()
    WHERE id IN (
      SELECT id FROM <jobs>
       WHERE (status='pending' AND run_after <= now())
          OR (status='processing' AND locked_at < now() - make_interval(secs => $lease))
       ORDER BY priority DESC, run_after
       LIMIT $batch
       FOR UPDATE SKIP LOCKED)
   RETURNING *;
   ```
   `$lease` = `WORKER_JOB_LEASE_SECONDS` (900): задача упавшего воркера снова доступна
   после истечения аренды.
2. **Работа** — без открытой транзакции и без удержания соединения (сеть, браузер, AI).
3. **Финализация** — каждая задача в своей короткой транзакции:
   - успех: `status='succeeded', last_error=NULL, locked_at=NULL, locked_by=NULL`
     (+ запись результата и, если нужно, событие в `events` в той же транзакции);
   - ошибка, если повторяема и `attempts < max_attempts`: `status='pending'`,
     `run_after = now() + min(30s * 2^(attempts-1), 6h)`, `last_error`, сброс аренды;
   - иначе `status='failed'` (dead letter: остаётся для разбора).

Постановка задач идемпотентна (уникальный ключ задачи + upsert): повторное событие не
создаёт дубликат; перезапуск завершённой задачи — `status='pending', attempts=0,
run_after=now()` с очисткой аренды и ошибки.

### Хранение

Модуль `maintenance` (раз в `MAINTENANCE_INTERVAL_SECONDS`) удаляет `succeeded`-доставки
старше `OUTBOX_RETENTION_DAYS` и события без оставшихся доставок; `failed` хранятся до
ручного разбора. Он же окончательно удаляет заметки из корзины старше
`TRASH_RETENTION_DAYS`, незавершённые загрузки старше 24 ч и осиротевшие префиксы
`objects/*` старше 24 ч (не более 200 за проход).

Мониторинг очередей:

```sql
SELECT consumer, status, count(*) FROM event_deliveries GROUP BY 1, 2;
SELECT status, count(*) FROM snapshot_jobs GROUP BY 1;
SELECT id, attempts, last_error FROM snapshot_jobs WHERE status = 'failed' ORDER BY updated_at DESC LIMIT 20;
```

## Фронтенд (`web/`)

React Router (SPA, `ssr: false`) + TanStack Query. Сборка — статические файлы
`build/client`, которые отдаёт Caddy (`/assets/*` — immutable-кэш, `index.html` — `no-cache`,
неизвестные пути → `index.html`). Обновления списков — через ленту изменений
`GET /api/v1/notes/changes?since=<cursor>` вместо полного опроса.

## Ресурсы (4 ГБ)

Лимиты памяти контейнеров: postgres 1 ГБ (`shared_buffers=512MB`), api 448 МБ,
worker 384 МБ, snapshot-worker 1.5 ГБ, telegram-bot 192 МБ, caddy 128 МБ. Каждый процесс
держит один пул соединений (`DB_POOL_SIZE` + `DB_MAX_OVERFLOW`), сумма далеко ниже
`max_connections=60`. Логи контейнеров ротируются (3 × 10 МБ).
