# Seyvix

Личная база заметок: тексты, ссылки, файлы, изображения, документы и медиа — с автоматическими
снимками страниц, извлечением текста, гибридным поиском (полнотекстовый + векторный),
автотегами и таксономией. Вход через Telegram, приём заметок через Telegram-бота и
Telegram Web App.

- `backend/` — FastAPI API + фоновые модули (`python -m app.worker ...`), PostgreSQL/pgvector.
- `web/` — SPA (React Router, TanStack Query); в продакшене — статика в образе Caddy.
- `telegram-bot/` — бот (aiogram), общается только с API.
- `docker-compose.yml` — весь стек (локально и на сервере), `docker-compose.dev.yml` — dev-оверлей.
- `scripts/` — `init-env.sh`, `deploy.sh`, `backup.sh`, `restore.sh`, `bootstrap-server.sh`.
- Архитектура и SQL-протокол очередей: [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).
  Правила разработки: [`AGENTS.md`](AGENTS.md).

Из инфраструктуры нужен только PostgreSQL. Файлы — в Docker-томе (или S3). AI — любой
OpenAI-совместимый API, необязателен.

## Быстрый старт (разработка)

Нужны Docker с compose ≥ 2.24 и `make`; для запуска тестов вне Docker — `uv` и Node 22.

```bash
make env     # .env из .env.example с сгенерированными секретами
make dev     # postgres + migrate + api (reload) + воркеры + Vite
```

- приложение: http://localhost:5173 (Vite проксирует `/api` в api);
- API и Swagger: http://localhost:8000/api/v1/docs;
- PostgreSQL: `localhost:5432` (только 127.0.0.1).

Dev-оверлей сам включает `APP_ENV=development` и dev-вход без Telegram
(`TELEGRAM_DEV_LOGIN_ENABLED`), dev-пользователь (`777001`) — администратор. Код `backend/`
и `web/` монтируется в контейнеры; после изменения зависимостей: `make dev` снова
(`--build`), для web — `docker compose -f docker-compose.yml -f docker-compose.dev.yml up --build -V web`.

Можно запускать Vite локально: `cd web && npm ci && npm run dev` (прокси на `localhost:8000`).

Тесты и проверки:

```bash
make testdb   # одноразовый Postgres для тестов на :55432 (таблицы пересоздаются!)
make lint     # ruff + mypy (backend), ruff (бот), tsc (web)
make test     # pytest backend и бота, тесты web
make config   # валидация compose-файлов
```

Продакшен-подобный запуск локально: `make up` (собирает образы, Caddy на http://localhost,
порт меняется `HTTP_PORT`).

## Деплой на сервер

Рассчитано на один сервер с 4 ГБ RAM (2 vCPU, 30+ ГБ диска), Ubuntu 22.04/24.04 или
Debian 12/13, архитектура amd64 (образы CI собираются под amd64).

### 1. Сервер

```bash
# под root: Docker, swap 2 ГБ, ufw (22/80/443), пользователь deploy, каталог /opt/seyvix
bash bootstrap-server.sh deploy /opt/seyvix
```

(файл — `scripts/bootstrap-server.sh` из репозитория). Вход по SSH для `deploy` — по ключу.

### 2. DNS и HTTPS

Создайте A (и AAAA, если есть IPv6) запись `seyvix.example.com` → IP сервера. В `.env`:

```env
SITE_ADDRESS=seyvix.example.com
PUBLIC_URL=https://seyvix.example.com
```

Caddy сам получит сертификат Let's Encrypt и будет его продлевать (сертификаты — в томе
`caddy_data`). Порты 80 и 443 (TCP, плюс 443/UDP для HTTP/3) должны быть доступны из
интернета. Только Caddy публикует порты; API, воркеры и БД наружу не открыты.

### 3. Конфигурация

На сервере в `/opt/seyvix` (CI сам кладёт туда `docker-compose.yml`, `.env.example` и
`scripts/`; для первого раза можно скопировать их вручную через `scp`):

```bash
scripts/init-env.sh   # сгенерирует POSTGRES_PASSWORD, AUTH_JWT_SECRET, TELEGRAM_INTERNAL_TOKEN
nano .env             # SITE_ADDRESS, PUBLIC_URL, ADMIN_TELEGRAM_IDS, TELEGRAM_*, AI_*
```

При `APP_ENV=production` API и воркеры не стартуют со слабыми/дефолтными секретами, без
`ADMIN_TELEGRAM_IDS` в режиме allowlist или с включённым dev-входом — смотрите
`docker compose logs migrate api`.

### 4. CI/CD (GitHub Actions)

`.github/workflows/ci.yml`: на каждый PR и push в `main` — ruff/mypy/pytest backend
(с pgvector), ruff/pytest бота, typecheck/test/build web, валидация compose и shellcheck.
На push в `main` дополнительно: сборка образов `api`, `worker-snapshots`, `web`,
`telegram-bot` → GHCR (`ghcr.io/<owner>/<repo>/<name>:<sha>` и `:latest`) → деплой по SSH:
копирует compose-файл и скрипты и выполняет `scripts/deploy.sh <sha> <prefix>`
(`pull` → `up -d --no-build --wait`; job падает, если сервис не стал healthy).

Секреты (Settings → Environments → `production`):

| секрет | значение |
|---|---|
| `DEPLOY_HOST` | адрес сервера |
| `DEPLOY_USER` | `deploy` |
| `DEPLOY_SSH_KEY` | приватный ключ (публичный — в `~deploy/.ssh/authorized_keys`) |
| `DEPLOY_KNOWN_HOSTS` | вывод `ssh-keyscan -p <port> <host>`, **проверенный** по отпечатку сервера |
| `DEPLOY_PORT` | необязательно, 22 |
| `DEPLOY_PATH` | необязательно, `/opt/seyvix` |

Для pull на сервере используется временный `GITHUB_TOKEN` (логин → pull → logout).

### 5. Первый запуск без CI

С образами из реестра: `docker login ghcr.io` и `scripts/deploy.sh <sha> ghcr.io/<owner>/<repo>`.
Или сборка прямо на сервере из клона репозитория: `docker compose up -d --build --wait`
(сборка snapshot-образа занимает несколько минут).

### Telegram

1. Создайте бота в @BotFather → `TELEGRAM_BOT_TOKEN`.
2. Вход на сайте: BotFather → Bot Settings → Web Login, redirect URL
   `https://<домен>/auth/callback` → `TELEGRAM_OIDC_CLIENT_ID`, `TELEGRAM_OIDC_CLIENT_SECRET`.
   Для виджета Telegram Login укажите домен сайта в BotFather (`/setdomain`).
3. Бот: `COMPOSE_PROFILES=telegram` в `.env` (и `TELEGRAM_INTERNAL_TOKEN`). При `https://`
   в `PUBLIC_URL` бот показывает кнопку Telegram Web App.

### Доступ (allowlist)

По умолчанию `ACCESS_MODE=allowlist`: войти и пользоваться ботом могут только
администраторы (`ADMIN_TELEGRAM_IDS`, через запятую) и пользователи с выданным доступом.
Выдавать/отзывать доступ: в веб-интерфейсе (раздел доступа в настройках, виден админам)
или командами бота `/allow <id|@username> [заметка]`, `/deny <id|@username>`, `/access`.
Отзыв доступа сразу завершает сессии пользователя. `ACCESS_MODE=open` — вход для всех.

### AI

Задайте `AI_API_KEY` (и при необходимости `AI_BASE_URL` — OpenAI, OpenRouter, vLLM,
Ollama `/v1` и т.п.) и модели `AI_*_MODEL`. Включаются: эмбеддинги и гибридный поиск,
автотеги, таксономия, OCR изображений; опционально описание изображений/видео
(`AI_VISION_ENABLED`), транскрипция аудио/видео (`AI_TRANSCRIPTION_ENABLED`), расширение
поисковых запросов (`AI_QUERY_EXPANSION_ENABLED`). Без ключа всё остальное работает,
поиск — полнотекстовый. `AI_EMBEDDING_DIMENSIONS` зашита в схему БД — выберите до
первого запуска.

## Переменные окружения

Полный список с комментариями — [`.env.example`](.env.example); все настройки и дефолты —
`backend/app/core/config.py` (имя поля в верхнем регистре = переменная).

| группа | переменные |
|---|---|
| сервер | `SITE_ADDRESS`, `HTTP_PORT`, `HTTPS_PORT`, `MAX_BODY_SIZE`, `COMPOSE_PROFILES`, `IMAGE_PREFIX`, `IMAGE_TAG` |
| приложение | `APP_ENV`, `PUBLIC_URL`, `LOG_LEVEL`, `MAX_UPLOAD_BYTES`, `CORS_ALLOWED_ORIGINS` |
| БД | `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD` |
| файлы | `STORAGE_BACKEND` (`local`/`s3`), `S3_*` |
| вход и доступ | `AUTH_JWT_SECRET`, `ACCESS_MODE`, `ADMIN_TELEGRAM_IDS`, `TELEGRAM_*` |
| AI | `AI_BASE_URL`, `AI_API_KEY`, `AI_*_MODEL`, `AI_EMBEDDING_DIMENSIONS`, `AI_*_ENABLED` |
| снимки | `SNAPSHOT_*_ENABLED`, `WORKER_SNAPSHOT_CONCURRENCY` |
| обслуживание | `TRASH_RETENTION_DAYS` |

## Бэкапы и восстановление

```bash
scripts/backup.sh            # backups/<UTC-время>/{db.dump, storage.tar.gz, env}
scripts/restore.sh backups/20260101T030000Z
```

`backup.sh` работает на живом стеке (pg_dump — консистентный снимок), удаляет бэкапы
старше `BACKUP_KEEP_DAYS` (14). При `STORAGE_BACKEND=s3` файлы бэкапьте средствами
провайдера. Каталог `backups/` содержит копию `.env` с секретами — храните копии вне
сервера (например, `rclone`/`rsync` на другой хост). Ежедневно через cron пользователя
`deploy`:

```cron
30 3 * * * cd /opt/seyvix && scripts/backup.sh >> backups/backup.log 2>&1
```

`restore.sh` останавливает приложение, пересоздаёт БД из дампа, заменяет файлы и
поднимает стек обратно. `.env` не перезаписывается — сверьте с `env` из бэкапа.

## Обновление и откат

- Обновление — push в `main` (CI задеплоит) или вручную `scripts/deploy.sh <sha>`.
  Миграции применяет сервис `migrate` перед стартом api и воркеров.
- Откат: `scripts/deploy.sh <предыдущий-sha>` — история в `.deploy-history`, последние три
  версии образов остаются на диске. Если новая версия меняла схему БД, откат кода без
  восстановления бэкапа может не подняться — делайте `scripts/backup.sh` перед рискованными
  обновлениями.
- Текущий тег хранится в `.env` (`IMAGE_TAG`), поэтому обычные `docker compose ...`
  на сервере работают с задеплоенной версией.

## Диагностика

```bash
docker compose ps                     # статусы и healthchecks
docker compose logs -f --tail=200 api # логи сервиса (api, worker, snapshot-worker, migrate, caddy)
curl -s https://<домен>/api/v1/health/ready  # готовность (БД + хранилище)
docker compose exec postgres psql -U seyvix seyvix
```

- **Сайт не открывается по HTTPS** — DNS указывает на сервер? 80/443 открыты? Ошибки
  ACME — в `docker compose logs caddy`. Let's Encrypt ограничивает частоту выпусков:
  не пересоздавайте том `caddy_data`.
- **api/воркеры перезапускаются** — `docker compose logs migrate api`: чаще всего
  проверка production-конфигурации (секреты, `ADMIN_TELEGRAM_IDS`).
- **Заметки не обрабатываются** (нет превью/текста/тегов) — `docker compose logs
  snapshot-worker worker`; состояние очередей — SQL из `docs/ARCHITECTURE.md`.
- **OOM / контейнер убит** (`docker compose ps` → exit 137) — снизьте
  `WORKER_SNAPSHOT_CONCURRENCY`, проверьте swap (`free -h`).
- **403 `access_denied` при входе** — пользователя нет в allowlist (см. «Доступ»).
- **413 при загрузке** — файл больше `MAX_UPLOAD_BYTES`/`MAX_BODY_SIZE`.

## Roadmap

- Теги на двух языках (сейчас английский, затем ещё русский).
- Саммери заметки по кнопке.
