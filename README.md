# Seyvix

Seyvix — личная база для заметок, ссылок и файлов. Приложение сохраняет материалы из Telegram
и веб-интерфейса, извлекает текст, делает снимки страниц и поддерживает поиск, теги и категории.

## Состав проекта

| Каталог или файл | Назначение |
|---|---|
| `backend/` | FastAPI, PostgreSQL/pgvector и фоновые обработчики |
| `web/` | Веб-интерфейс на React |
| `telegram-bot/` | Telegram-бот, работающий через API |
| `docker-compose.yml` | Основной стек для локального и серверного запуска |
| `docker-compose.dev.yml` | Локальная разработка с горячей перезагрузкой и Vite |
| `scripts/` | Настройка окружения, деплой, резервное копирование и восстановление |

Файлы хранятся в Docker-томе или S3-совместимом хранилище. Для базы данных используется
PostgreSQL. AI-функции настраиваются отдельно и могут быть выключены.

## Локальная разработка

Нужны Docker Compose 2.24 или новее и `make`.

```bash
make env     # создать .env и сгенерировать секреты
make dev     # запустить БД, миграции, API, воркеры и Vite
```

После запуска:

- веб-приложение: http://localhost:5173;
- API и Swagger: http://localhost:8000/api/v1/docs;
- PostgreSQL: `localhost:5432`, доступен только с этого компьютера.

Dev-конфигурация включает вход без Telegram. Локальный пользователь с ID `777001` —
администратор. Исходники `backend/` и `web/` подключены к контейнерам; изменения кода
подхватываются автоматически. После изменения зависимостей пересоберите нужный контейнер:

```bash
make dev
docker compose -f docker-compose.yml -f docker-compose.dev.yml up --build -V web
```

Остановить dev-стек можно командой `make dev-down`. Если запускаете Vite на компьютере,
а не в Docker, используйте `cd web && npm ci && npm run dev`; API должен быть запущен отдельно.

Полезные проверки:

```bash
make lint     # линтеры и проверка типов
make test     # тесты backend, Telegram-бота и web
make config   # проверить Docker Compose конфигурацию
```

`make testdb` поднимает отдельную временную тестовую БД на порту `55432`. Тесты очищают её
таблицы; рабочую БД на `5432` они не используют. Для запуска production-подобного стека
локально используйте `make up` — он собирает образы и запускает Caddy на `localhost`.

## Развёртывание на сервере

Поддерживаемая конфигурация: один сервер с 4 ГБ RAM, 2 vCPU и 30 ГБ свободного диска,
Ubuntu 22.04/24.04 или Debian 12/13, архитектура amd64.

### 1. Подготовить сервер

Из клона репозитория выполните скрипт от `root`. Он установит Docker, настроит swap и firewall,
создаст пользователя `deploy` и каталог `/opt/seyvix`:

```bash
bash scripts/bootstrap-server.sh deploy /opt/seyvix
```

Для SSH-входа пользователя `deploy` настройте ключи.

### 2. Настроить домен и HTTPS

Направьте DNS-запись A (и AAAA, если сервер доступен по IPv6) на его IP. В `.env` укажите:

```env
SITE_ADDRESS=seyvix.example.com
PUBLIC_URL=https://seyvix.example.com
```

Caddy автоматически получает и продлевает сертификат Let's Encrypt. Для этого из интернета
должны быть доступны порты 80 и 443 TCP; UDP 443 используется для HTTP/3. Наружу опубликованы
только порты Caddy — API, воркеры и PostgreSQL напрямую недоступны.

### 3. Создать конфигурацию

Каталог `/opt/seyvix` должен содержать `docker-compose.yml`, `.env.example` и `scripts/`.
CI копирует эти файлы при деплое; для первого запуска без CI перенесите их на сервер вручную.
Затем выполните:

```bash
cd /opt/seyvix
scripts/init-env.sh   # создаст .env и сгенерирует обязательные секреты
nano .env             # укажите домен, PUBLIC_URL, ADMIN_TELEGRAM_IDS и нужные интеграции
```

В режиме `APP_ENV=production` API не запустится со слабыми секретами, без администратора в
режиме `allowlist` или с включённым dev-входом. Причину смотрите в логах `migrate` и `api`.

### 4. Запустить первый релиз

Если собираете образы на сервере из клона репозитория:

```bash
docker compose up -d --build --wait
```

Если используете образы CI, войдите в реестр и запустите скрипт деплоя с тегом сборки:

```bash
docker login ghcr.io
scripts/deploy.sh <git-sha> ghcr.io/<owner>/seyvix
```

### Автоматический деплой через GitHub Actions

Workflow `.github/workflows/ci.yml` проверяет PR и каждый push: запускает линтеры, тесты,
проверку типов и Compose-конфигурации. Успешный push в `main` дополнительно собирает образы,
публикует их в GHCR и развёртывает на сервере. Деплой ждёт, пока сервисы станут healthy.

В GitHub добавьте в **Settings → Environments → production → Environment secrets**:

| Секрет | Значение |
|---|---|
| `DEPLOY_HOST` | адрес сервера |
| `DEPLOY_USER` | `deploy` |
| `DEPLOY_SSH_KEY` | приватный SSH-ключ; публичный ключ должен быть на сервере |
| `DEPLOY_KNOWN_HOSTS` | проверенный отпечаток сервера для SSH |
| `DEPLOY_PORT` | необязательно; по умолчанию `22` |
| `DEPLOY_PATH` | необязательно; по умолчанию `/opt/seyvix` |

Workflow использует временный `GITHUB_TOKEN`, чтобы скачать образы из GHCR.

### Telegram

1. Создайте бота через `@BotFather` и укажите токен в `TELEGRAM_BOT_TOKEN`.
2. В BotFather включите **Bot Settings → Web Login**. Redirect URL должен быть
   `https://<домен>/auth/callback`; client ID и secret запишите в `TELEGRAM_OIDC_CLIENT_ID`
   и `TELEGRAM_OIDC_CLIENT_SECRET`. Для виджета входа укажите домен через `/setdomain`.
3. Чтобы запустить самого бота, добавьте `telegram` в `COMPOSE_PROFILES` и задайте
   `TELEGRAM_INTERNAL_TOKEN`. При HTTPS в `PUBLIC_URL` бот также покажет кнопку Telegram Web App.

### Доступ (allowlist)

По умолчанию `ACCESS_MODE=allowlist`: войти могут администраторы из `ADMIN_TELEGRAM_IDS` и
пользователи, которым выдали доступ. Администратор может управлять доступом в настройках сайта
или командами бота `/allow <id|@username> [заметка]`, `/deny <id|@username>` и `/access`.
Отзыв доступа завершает сессии пользователя. `ACCESS_MODE=open` разрешает вход всем.

### AI

AI настраивается в `.env`; полный пример есть в [`.env.example`](.env.example). В текущей
конфигурации используются модели `deepseek-v4.1-flash:free` для чата и `jina-embeddings-v5-text-small`
для эмбеддингов. `AI_API_KEY` включает AI-функции и используется для чата; без него AI-обработка
отключена. Для Jina задайте отдельный `AI_EMBEDDING_API_KEY`. Ключи и API-адреса для чата и
эмбеддингов настраиваются отдельно через `AI_API_KEY`, `AI_EMBEDDING_API_KEY`, `AI_BASE_URL` и
`AI_EMBEDDING_BASE_URL`. Если для обеих возможностей используется один провайдер, embedding-ключ
можно не задавать — приложение использует `AI_API_KEY`. Не помещайте ключи во frontend
или в git: сервер отправляет настроенным облачным API тексты заметок и запросы поиска.

Суффикс `:free` ограничивает модель бесплатным маршрутом: если его лимит исчерпан, запрос
завершится ошибкой и не перейдёт на платный маршрут. Бесплатные квоты и доступность моделей
могут меняться.

Vision, транскрибация аудио и расширение поискового запроса выключены по умолчанию. Их можно
включить переменными `AI_VISION_ENABLED`, `AI_TRANSCRIPTION_ENABLED` и
`AI_QUERY_EXPANSION_ENABLED`. Для отдельного API или ключа предусмотрены настройки
`AI_VISION_*` и `AI_TRANSCRIPTION_*`.

Для поиска используются два режима Jina: `retrieval.passage` для документов и `retrieval.query`
для поисковых запросов. Размерность вектора задаётся через `AI_EMBEDDING_DIMENSIONS` и должна
совпадать с ответом модели. В одной установке БД хранит векторы одной embedding-модели и одной
размерности.

Если модель меняется, воркер пересчитает векторы источников, сохранённых под другим именем
модели. Если существующая БД использует другую размерность, миграция `0002` сбросит только
несовместимые векторы, сохранит тексты чанков и поставит их на повторную векторизацию; заметки
и файлы она не удаляет. При совпадающей размерности эта миграция векторы не сбрасывает.
Изменение размерности в `.env` после применения миграции само по себе не меняет схему БД:
потребуется новая миграция или пересоздание БД. Если изменить только `AI_EMBEDDING_TASK` при том
же имени модели, векторы не будут обнаружены как устаревшие — настройте task до первой
индексации либо выполните переиндексацию отдельно.

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
