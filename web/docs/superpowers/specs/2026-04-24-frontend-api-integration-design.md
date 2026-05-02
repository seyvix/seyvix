---
name: Frontend–API Integration & Telegram OAuth
description: Интеграция web (Vite/React) с api (FastAPI/Docker), настройка dev-окружения и Telegram OAuth redirect-flow
type: project
---

# Frontend–API Integration & Telegram OAuth — Design Spec

**Дата:** 2026-04-24
**Статус:** approved

---

## Контекст

В проекте два сервиса:

- **api** — FastAPI, запускается в Docker (postgres + redis), порт 8000.
- **web** — React 19 + Vite, запускается локально, порт 5173.

Backend уже полностью реализовал Telegram OAuth (redirect-flow + one-time code exchange). Фронтенд имеет AuthPage с 3D-кнопкой Telegram, AuthContext с токенами в памяти и apiClient с авто-refresh. Связи между сервисами нет: нет Vite-прокси, нет CORS, нет frontend callback-страницы для обмена кода.

---

## Цели

1. Запустить оба сервиса локально и соединить их.
2. Реализовать полноценный Telegram OAuth (redirect-flow, Вариант A).
3. Подготовить ngrok-инструкцию для тестирования с реальным Telegram-ботом.

---

## Архитектура

```
[Browser]
    │
    ├── localhost:5173 (Vite dev server)
    │       │
    │       └── /api/* ──proxy──► localhost:8000 (API Docker)
    │
    └── https://xxx.ngrok.io (ngrok tunnel → localhost:5173)
            │
            └── /api/* ──proxy──► localhost:8000
```

В DEV ngrok опционален (только для реального Telegram Widget). Для dev-login достаточно `localhost:5173`.

---

## Режим запуска

| Компонент | Команда | Порт |
|---|---|---|
| PostgreSQL + Redis | `docker compose up -d postgres redis` (из `api/`) | 5432, 6379 |
| API (с hot-reload) | `docker compose -f docker-compose.yml -f docker-compose.dev.yml up --build` | 8000 |
| Web | `npm run dev` (из `web/`) | 5173 |
| ngrok (для реального Telegram) | `ngrok http 5173` | - |

---

## Файлы изменений

### Backend: `api/.env`

Создаётся один раз вручную. Ключевые переменные:

```env
TELEGRAM_BOT_TOKEN=<токен от @BotFather>
TELEGRAM_LOGIN_REDIRECT_URL=http://localhost:5173/auth/callback
TELEGRAM_DEV_LOGIN_ENABLED=true
CORS_ALLOWED_ORIGINS=["http://localhost:5173"]
```

При запуске через ngrok — заменить `http://localhost:5173` на `https://xxx.ngrok.io` в обоих полях.

### Frontend: `web/vite.config.ts`

Добавить proxy-секцию:

```ts
server: {
  proxy: {
    '/api': {
      target: 'http://localhost:8000',
      changeOrigin: true,
    },
  },
},
```

### Frontend: `web/src/api/auth.ts`

Добавить функцию обмена кода:

```ts
export async function apiTelegramCode(code: string): Promise<AuthTokensResponse>
```

Вызов: `POST /api/v1/auth/telegram-code` с телом `{ code }`.

### Frontend: `web/src/pages/AuthCallbackPage.tsx` (новый)

Страница без UI (только логика). При монтировании:
1. Читает `?code` и `?error` из URL.
2. Если `error` — редирект на `/auth?error=<code>`.
3. Если `code` — вызывает `apiTelegramCode(code)`.
4. Успех: сохраняет токен через `AuthContext`, редирект на `/notes`.
5. Ошибка: редирект на `/auth?error=telegram_code_failed`.

Показывает минимальный лоадер пока идёт запрос.

### Frontend: `web/src/App.tsx`

Добавить публичный роут `/auth/callback` (вне `RequireAuth`):

```tsx
{
  path: '/auth/callback',
  lazy: async () => ({ Component: (await import('./pages/AuthCallbackPage')).default }),
},
```

### Frontend: `web/src/pages/AuthPage.tsx`

Изменить `handleClick`. Условие выбора flow — наличие переменной `VITE_TELEGRAM_BOT_ID`:

- **Если `VITE_TELEGRAM_BOT_ID` не задан** → `window.location.href = '/api/v1/auth/telegram-dev-login'`
- **Если `VITE_TELEGRAM_BOT_ID` задан** → `window.location.href = buildTelegramOAuthUrl()` — формирует URL вида:
  `https://oauth.telegram.org/auth?bot_id=VITE_TELEGRAM_BOT_ID&origin=window.location.origin&return_to=window.location.origin/api/v1/auth/telegram-callback`

Это позволяет переключаться между dev-login и реальным Telegram при `npm run dev` — достаточно добавить/убрать переменную в `web/.env.local`.

Также обработать `?error` из URL — показать сообщение об ошибке если редирект пришёл с ошибкой.

### Frontend: `web/.env.local` (для реального Telegram при dev)

```env
VITE_TELEGRAM_BOT_ID=<числовой bot_id из @BotFather>
```

Без этого файла AuthPage использует dev-login.

---

## Telegram OAuth Flows

### DEV flow (без реального бота)

```
1. Клик → GET /api/v1/auth/telegram-dev-login
2. API создаёт dev-пользователя и сессию
3. API redirect → /auth/callback?code=<one-time-code>
4. AuthCallbackPage: POST /api/v1/auth/telegram-code { code }
5. API возвращает { user, access_token }
6. Сохранить token в tokenRef, setUser(user), redirect /notes
```

Требует: `TELEGRAM_DEV_LOGIN_ENABLED=true` и `TELEGRAM_LOGIN_REDIRECT_URL` в `.env`.

### PROD flow (реальный Telegram + ngrok)

```
1. Клик → window.location.href = https://oauth.telegram.org/auth?bot_id=...&return_to=NGROK/api/v1/auth/telegram-callback
2. Telegram показывает подтверждение
3. Telegram → GET NGROK/api/v1/auth/telegram-callback?id=...&first_name=...&hash=...
4. Vite proxy → API → верифицирует подпись
5. API redirect → NGROK/auth/callback?code=<one-time-code>
6. AuthCallbackPage: POST /api/v1/auth/telegram-code { code }
7. Сохранить token, redirect /notes
```

Требует: `TELEGRAM_BOT_TOKEN` в `.env`, ngrok-туннель, домен бота настроен в @BotFather.

---

## Пошаговый гайд запуска

### Шаг 1: Подготовить api/.env

```bash
cd api
cp .env.example .env   # если пример есть, иначе создать вручную
# Заполнить TELEGRAM_BOT_TOKEN, TELEGRAM_LOGIN_REDIRECT_URL, CORS_ALLOWED_ORIGINS
```

### Шаг 2: Запустить API

```bash
cd api
docker compose -f docker-compose.yml -f docker-compose.dev.yml up --build
```

Проверка: `curl http://localhost:8000/api/v1/health` → `{"status":"ok"}`

### Шаг 3: Запустить Web

```bash
cd web
npm install
npm run dev
```

Проверка: открыть `http://localhost:5173` — должна открыться AuthPage.

### Шаг 4: Тест DEV auth

Открыть `http://localhost:5173` → кликнуть кнопку Telegram → должна пройти авторизация dev-пользователя → редирект на `/notes`.

### Шаг 5: Настроить реальный Telegram OAuth (ngrok)

```bash
ngrok http 5173
# Получить URL вида https://abc123.ngrok.io
```

В `api/.env` обновить:
```env
TELEGRAM_LOGIN_REDIRECT_URL=https://abc123.ngrok.io/auth/callback
CORS_ALLOWED_ORIGINS=["https://abc123.ngrok.io"]
```

В @BotFather: `/setdomain` → ввести `abc123.ngrok.io` (без `https://`, без порта).

Перезапустить API:
```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml up --build
```

Открыть `https://abc123.ngrok.io` в браузере → войти через Telegram.

---

## Граничные случаи

| Ситуация | Поведение |
|---|---|
| `?error=invalid_telegram_login` в callback | Редирект на `/auth?error=invalid_telegram_login` |
| `apiTelegramCode` вернул ошибку | Редирект на `/auth?error=telegram_code_failed` |
| Нет `?code` и нет `?error` в URL callback | Редирект на `/auth` |
| Telegram callback открыт напрямую без параметров | Редирект на `/auth` |
| `TELEGRAM_DEV_LOGIN_ENABLED=false` в dev | API вернёт 404 — показать ошибку на AuthPage |

---

## Что не меняется

- Логика `access_token` в памяти (tokenRef) — не трогаем.
- Авто-refresh при 401 в apiClient — не трогаем.
- Логика register/login по email — не трогаем.
- Структура модулей API — не трогаем.
