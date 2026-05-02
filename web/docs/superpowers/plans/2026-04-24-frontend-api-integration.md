# Frontend–API Integration & Telegram OAuth Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Соединить web (Vite/React, порт 5173) с api (FastAPI/Docker, порт 8000), исправить расхождение контрактов `UserResponse`, и реализовать Telegram OAuth redirect-flow от кнопки до `/notes`.

**Architecture:** Vite proxy пробрасывает `/api/*` на `localhost:8000`. MSW auth-перехватчики удаляются (они блокируют реальный `/auth/refresh`). Telegram OAuth: клик → `/telegram-dev-login` (dev) или `oauth.telegram.org` (prod) → API верифицирует → редирект на `/auth/callback?code=xxx` → обмен кода на токен → `loginWithTokens()` → `/notes`.

**Tech Stack:** React 19, TypeScript, Vite proxy, FastAPI Docker, MSW (только notes/folders), ngrok (для реального Telegram бота)

---

## File Map

| Файл | Действие | Зачем |
|---|---|---|
| `api/.env` | Создать | Бот-токен, redirect URL, CORS, dev-login флаг |
| `web/vite.config.ts` | Изменить | Добавить proxy `/api → localhost:8000` |
| `web/src/api/auth.ts` | Изменить | Исправить `UserResponse` + добавить `apiTelegramCode` |
| `web/src/mocks/browser.ts` | Изменить | Убрать `authHandlers` из MSW (они перехватывают реальный `/auth/refresh`) |
| `web/src/mocks/handlers/auth.ts` | Удалить | Больше не нужен — auth идёт через реальный API |
| `web/src/contexts/AuthContext.tsx` | Изменить | Убрать `mockLogin`, добавить `loginWithTokens` с `useCallback` |
| `web/src/pages/AuthCallbackPage.tsx` | Создать | Читает `?code`/`?error`, обменивает на токен, редирект |
| `web/src/App.tsx` | Изменить | Добавить публичный роут `/auth/callback` |
| `web/src/pages/AuthPage.tsx` | Изменить | Убрать `mockLogin`, добавить логику `VITE_TELEGRAM_BOT_ID` + отображение ошибок |

---

## Task 1: Создать `api/.env` и запустить API

**Files:**
- Create: `api/.env`

- [ ] **Шаг 1: Создать `api/.env` на основе примера**

```bash
cd /path/to/seyvix/api
cp .env.example .env
```

Отредактировать `.env`, установив следующие значения (остальные можно оставить из примера):

```env
TELEGRAM_BOT_TOKEN=<вставь токен из @BotFather>
TELEGRAM_LOGIN_REDIRECT_URL=http://localhost:5173/auth/callback
TELEGRAM_DEV_LOGIN_ENABLED=true
CORS_ALLOWED_ORIGINS=["http://localhost:5173"]
```

> `TELEGRAM_BOT_TOKEN` нужен для проверки подписи даже в dev-login flow. Если токена ещё нет — можно поставить любую строку, dev-login не проверяет подпись Telegram.

- [ ] **Шаг 2: Запустить API в dev-режиме**

```bash
cd api
docker compose -f docker-compose.yml -f docker-compose.dev.yml up --build
```

Ждём сообщений `postgres healthy`, `redis healthy`, `api started`.

- [ ] **Шаг 3: Проверить что API отвечает**

```bash
curl http://localhost:8000/api/v1/health
```

Ожидаемый ответ:
```json
{"status":"ok"}
```

- [ ] **Шаг 4: Проверить CORS-заголовки**

```bash
curl -v -H "Origin: http://localhost:5173" \
  http://localhost:8000/api/v1/health 2>&1 | grep -i "access-control"
```

Ожидаем: строку `access-control-allow-origin: http://localhost:5173`.

- [ ] **Шаг 5: Коммит (env-файл намеренно НЕ коммитим)**

`api/.env` не трогаем — он в `.gitignore`. Задача 1 завершена.

---

## Task 2: Добавить Vite proxy

**Files:**
- Modify: `web/vite.config.ts`

- [ ] **Шаг 1: Открыть `web/vite.config.ts`**

Текущее содержимое:
```ts
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
})
```

- [ ] **Шаг 2: Добавить секцию `server.proxy`**

Заменить содержимое `web/vite.config.ts` на:

```ts
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
    },
  },
})
```

- [ ] **Шаг 3: Запустить web и проверить прокси**

```bash
cd web
npm run dev
```

В другом терминале:
```bash
curl http://localhost:5173/api/v1/health
```

Ожидаемый ответ:
```json
{"status":"ok"}
```

Если ответ получен — прокси работает.

- [ ] **Шаг 4: Коммит**

```bash
cd web
git add vite.config.ts
git commit -m "feat: add vite proxy for api"
```

---

## Task 3: Исправить контракт `UserResponse` и добавить `apiTelegramCode`

**Files:**
- Modify: `web/src/api/auth.ts`

**Проблема:** Фронтенд имеет `UserResponse.email`, бэкенд возвращает `telegram_id`, `telegram_username`, `telegram_photo_url` вместо него.

- [ ] **Шаг 1: Обновить `UserResponse` и добавить `apiTelegramCode`**

Открыть `web/src/api/auth.ts`. Заменить интерфейс `UserResponse` и добавить новую функцию в конец файла.

Итоговый файл `web/src/api/auth.ts`:

```ts
const BASE = '/api/v1/auth'

export interface UserResponse {
  id: string
  telegram_id: string
  telegram_username: string | null
  telegram_photo_url: string | null
  display_name: string
  is_active: boolean
}

export interface AuthTokensResponse {
  user: UserResponse
  access_token: string
  token_type: string
}

export interface ApiError {
  code: string
  message: string
  details: unknown
}

export class AuthApiError extends Error {
  constructor(
    public readonly status: number,
    public readonly code: string,
    message: string,
  ) {
    super(message)
  }
}

async function parseError(res: Response): Promise<AuthApiError> {
  try {
    const body = await res.json()
    const err: ApiError = body.error ?? body
    return new AuthApiError(res.status, err.code ?? 'unknown_error', err.message ?? 'Unknown error')
  } catch {
    return new AuthApiError(res.status, 'unknown_error', res.statusText)
  }
}

export async function apiRegister(
  email: string,
  display_name: string,
  password: string,
): Promise<AuthTokensResponse> {
  const res = await fetch(`${BASE}/register`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email, display_name, password }),
    credentials: 'include',
  })
  if (!res.ok) throw await parseError(res)
  return res.json()
}

export async function apiLogin(
  email: string,
  password: string,
): Promise<AuthTokensResponse> {
  const res = await fetch(`${BASE}/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email, password }),
    credentials: 'include',
  })
  if (!res.ok) throw await parseError(res)
  return res.json()
}

export async function apiRefresh(): Promise<AuthTokensResponse> {
  const res = await fetch(`${BASE}/refresh`, {
    method: 'POST',
    credentials: 'include',
  })
  if (!res.ok) throw await parseError(res)
  return res.json()
}

export async function apiLogout(): Promise<void> {
  await fetch(`${BASE}/logout`, {
    method: 'POST',
    credentials: 'include',
  })
}

export async function apiTelegramCode(code: string): Promise<AuthTokensResponse> {
  const res = await fetch(`${BASE}/telegram-code`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ code }),
    credentials: 'include',
  })
  if (!res.ok) throw await parseError(res)
  return res.json()
}
```

- [ ] **Шаг 2: Убедиться что TypeScript не ругается**

```bash
cd web
npx tsc --noEmit
```

Ожидаем: нет ошибок (или только ошибки не связанные с нашими изменениями).

- [ ] **Шаг 3: Коммит**

```bash
git add src/api/auth.ts
git commit -m "fix: align UserResponse with backend schema, add apiTelegramCode"
```

---

## Task 4: Убрать MSW auth-перехватчики

**Files:**
- Modify: `web/src/mocks/browser.ts`
- Delete: `web/src/mocks/handlers/auth.ts`

**Проблема:** MSW перехватывает `POST /api/v1/auth/refresh` и возвращает `401`, пока `mockAuthenticated = false`. После реального Telegram-логина рефреш-кука выставлена, но MSW не знает об этом → разлогинивает пользователя при перезагрузке страницы.

MSW-обработчики notes/folders используют `/api/notes` и `/api/folders` (без `/v1/`) и не конфликтуют с реальным API — их оставляем.

- [ ] **Шаг 1: Убрать `authHandlers` из MSW worker**

Открыть `web/src/mocks/browser.ts`. Заменить содержимое:

```ts
import { setupWorker } from 'msw/browser'
import { noteHandlers } from './handlers/notes'
import { folderHandlers } from './handlers/folders'

export const worker = setupWorker(...noteHandlers, ...folderHandlers)
```

- [ ] **Шаг 2: Удалить `web/src/mocks/handlers/auth.ts`**

```bash
rm web/src/mocks/handlers/auth.ts
```

- [ ] **Шаг 3: Проверить TypeScript**

```bash
cd web
npx tsc --noEmit
```

Ожидаем: нет ошибок на `auth.ts` (файл удалён, импорт тоже убран из `browser.ts`).

- [ ] **Шаг 4: Коммит**

```bash
git add src/mocks/browser.ts
git rm src/mocks/handlers/auth.ts
git commit -m "fix: remove msw auth interceptors, auth now goes through real api"
```

---

## Task 5: Обновить `AuthContext` — убрать `mockLogin`, добавить `loginWithTokens`

**Files:**
- Modify: `web/src/contexts/AuthContext.tsx`

- [ ] **Шаг 1: Заменить содержимое `web/src/contexts/AuthContext.tsx`**

```tsx
import { createContext, useCallback, useContext, useEffect, useRef, useState } from 'react'
import { apiLogin, apiLogout, apiRefresh, apiRegister } from '../api/auth'
import type { UserResponse } from '../api/auth'
import { configureApiClient } from '../lib/apiClient'

interface AuthContextValue {
  user: UserResponse | null
  isReady: boolean
  login: (email: string, password: string) => Promise<void>
  register: (email: string, display_name: string, password: string) => Promise<void>
  logout: () => Promise<void>
  loginWithTokens: (user: UserResponse, accessToken: string) => void
}

const AuthContext = createContext<AuthContextValue | null>(null)

export function useAuth() {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used within AuthProvider')
  return ctx
}

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<UserResponse | null>(null)
  const [isReady, setIsReady] = useState(false)

  // access_token живёт только в памяти
  const tokenRef = useRef<string | null>(null)

  // Настраиваем apiClient сразу — он будет использоваться в api/notes.ts
  useEffect(() => {
    configureApiClient({
      getToken: () => tokenRef.current,
      setToken: (t) => { tokenRef.current = t },
      onUnauthenticated: () => {
        tokenRef.current = null
        setUser(null)
      },
    })
  }, [])

  // Bootstrap: пробуем refresh при старте приложения
  useEffect(() => {
    apiRefresh()
      .then(({ user, access_token }) => {
        tokenRef.current = access_token
        setUser(user)
      })
      .catch(() => {
        // refresh не удался — пользователь не авторизован, это нормально
      })
      .finally(() => {
        setIsReady(true)
      })
  }, [])

  async function login(email: string, password: string) {
    const { user, access_token } = await apiLogin(email, password)
    tokenRef.current = access_token
    setUser(user)
  }

  async function register(email: string, display_name: string, password: string) {
    const { user, access_token } = await apiRegister(email, display_name, password)
    tokenRef.current = access_token
    setUser(user)
  }

  async function logout() {
    await apiLogout()
    tokenRef.current = null
    setUser(null)
  }

  // useCallback даёт стабильную ссылку — useEffect в AuthCallbackPage не зациклится
  const loginWithTokens = useCallback((user: UserResponse, accessToken: string) => {
    tokenRef.current = accessToken
    setUser(user)
  }, [])

  return (
    <AuthContext.Provider value={{ user, isReady, login, register, logout, loginWithTokens }}>
      {children}
    </AuthContext.Provider>
  )
}
```

- [ ] **Шаг 2: Проверить TypeScript**

```bash
cd web
npx tsc --noEmit
```

Ожидаем: нет ошибок.

- [ ] **Шаг 3: Коммит**

```bash
git add src/contexts/AuthContext.tsx
git commit -m "refactor: replace mockLogin with loginWithTokens in AuthContext"
```

---

## Task 6: Создать `AuthCallbackPage.tsx`

**Files:**
- Create: `web/src/pages/AuthCallbackPage.tsx`

Страница обрабатывает редирект от API после Telegram OAuth. Читает `?code` или `?error` из URL, обменивает код на токен, сохраняет через `loginWithTokens`, редиректит на `/notes`.

- [ ] **Шаг 1: Создать `web/src/pages/AuthCallbackPage.tsx`**

```tsx
import { useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { apiTelegramCode } from '../api/auth'
import { useAuth } from '../contexts/AuthContext'

export default function AuthCallbackPage() {
  const navigate = useNavigate()
  const { loginWithTokens } = useAuth()

  useEffect(() => {
    const params = new URLSearchParams(window.location.search)
    const code = params.get('code')
    const error = params.get('error')

    if (error) {
      navigate(`/auth?error=${encodeURIComponent(error)}`, { replace: true })
      return
    }

    if (!code) {
      navigate('/auth', { replace: true })
      return
    }

    apiTelegramCode(code)
      .then(({ user, access_token }) => {
        loginWithTokens(user, access_token)
        navigate('/notes', { replace: true })
      })
      .catch(() => {
        navigate('/auth?error=telegram_code_failed', { replace: true })
      })
  }, [navigate, loginWithTokens])

  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        height: '100vh',
      }}
    >
      <p style={{ color: 'var(--color-text-secondary, #888)', fontFamily: 'inherit' }}>
        Авторизация…
      </p>
    </div>
  )
}
```

- [ ] **Шаг 2: Проверить TypeScript**

```bash
cd web
npx tsc --noEmit
```

Ожидаем: нет ошибок.

- [ ] **Шаг 3: Коммит**

```bash
git add src/pages/AuthCallbackPage.tsx
git commit -m "feat: add AuthCallbackPage to handle telegram oauth code exchange"
```

---

## Task 7: Добавить роут `/auth/callback` в `App.tsx`

**Files:**
- Modify: `web/src/App.tsx`

Роут должен быть полностью публичным — вне `RequireAuth` и `RequireGuest`. Это важно: пользователь только что пришёл с Telegram и ещё не авторизован в контексте.

- [ ] **Шаг 1: Добавить роут в `web/src/App.tsx`**

Найти в файле массив роутов (первый аргумент `createBrowserRouter`). Добавить новый объект **первым** в массиве, до блока `RequireGuest`:

```tsx
const router = createBrowserRouter([
  // Полностью открытый роут — обрабатывает Telegram redirect с ?code или ?error
  {
    path: '/auth/callback',
    lazy: async () => ({ Component: (await import('./pages/AuthCallbackPage')).default }),
  },
  // Публичный роут — без сайдбара
  {
    element: <RequireGuest />,
    children: [
      {
        path: '/auth',
        lazy: async () => ({ Component: (await import('./pages/AuthPage')).default }),
      },
    ],
  },
  // Защищённые роуты — с сайдбаром
  {
    element: <RequireAuth />,
    children: [
      {
        element: <AppLayout />,
        children: [
          {
            index: true,
            element: <Navigate to="/notes" replace />,
          },
          {
            path: '/notes',
            lazy: async () => ({ Component: (await import('./pages/NotesPage')).default }),
          },
          {
            path: '/notes/:noteSlug',
            lazy: async () => ({ Component: (await import('./pages/NotePage')).default }),
          },
          {
            path: '/notes/:noteSlug/edit',
            lazy: async () => ({ Component: (await import('./pages/NoteEditPage')).default }),
          },
          {
            path: '/folders',
            lazy: async () => ({ Component: (await import('./pages/FoldersPage')).default }),
          },
          {
            path: '/folders/:folderSlug',
            lazy: async () => ({ Component: (await import('./pages/FolderPage')).default }),
          },
        ],
      },
    ],
  },
])
```

- [ ] **Шаг 2: Проверить TypeScript**

```bash
cd web
npx tsc --noEmit
```

Ожидаем: нет ошибок.

- [ ] **Шаг 3: Коммит**

```bash
git add src/App.tsx
git commit -m "feat: add public /auth/callback route for telegram oauth"
```

---

## Task 8: Обновить `AuthPage.tsx` — реальный Telegram OAuth вместо `mockLogin`

**Files:**
- Modify: `web/src/pages/AuthPage.tsx`

Логика кнопки:
- Если `VITE_TELEGRAM_BOT_ID` **не задан** → редирект на `/api/v1/auth/telegram-dev-login`
- Если `VITE_TELEGRAM_BOT_ID` **задан** → редирект на `https://oauth.telegram.org/auth?...`

Также добавляем отображение ошибки если `?error` передан в URL (например после неудачного обмена кода).

- [ ] **Шаг 1: Заменить содержимое `web/src/pages/AuthPage.tsx`**

```tsx
import { useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { motion, useMotionValue, useTransform, useSpring } from 'framer-motion'
import CircularText from '../components/CircularText/CircularText'
import styles from './AuthPage.module.css'

function TelegramLogo() {
  return (
    <img
      src="/telegramLogo.svg"
      alt="Telegram"
      className={styles.logo}
      draggable={false}
    />
  )
}

function TelegramIcon3D({ onClick }: { onClick: () => void }) {
  const mouseX = useMotionValue(0)
  const mouseY = useMotionValue(0)

  const rotateX = useSpring(useTransform(mouseY, [-0.5, 0.5], [18, -18]), { stiffness: 300, damping: 30 })
  const rotateY = useSpring(useTransform(mouseX, [-0.5, 0.5], [-18, 18]), { stiffness: 300, damping: 30 })

  function handleMouseMove(e: React.MouseEvent<HTMLDivElement>) {
    const rect = e.currentTarget.getBoundingClientRect()
    mouseX.set((e.clientX - rect.left) / rect.width - 0.5)
    mouseY.set((e.clientY - rect.top) / rect.height - 0.5)
  }

  function handleMouseLeave() {
    mouseX.set(0)
    mouseY.set(0)
  }

  return (
    <motion.div
      className={styles.iconWrapper}
      style={{ rotateX, rotateY, transformStyle: 'preserve-3d' }}
      onMouseMove={handleMouseMove}
      onMouseLeave={handleMouseLeave}
      whileTap={{ scale: 0.93 }}
      whileHover={{ scale: 1.06 }}
      transition={{ type: 'spring', stiffness: 300, damping: 20 }}
      onClick={onClick}
    >
      <TelegramLogo />
      <motion.div
        className={styles.iconShadow}
        style={{
          rotateX: useTransform(rotateX, v => -v * 0.5),
          rotateY: useTransform(rotateY, v => -v * 0.5),
        }}
      />
    </motion.div>
  )
}

const ERROR_MESSAGES: Record<string, string> = {
  invalid_telegram_login: 'Ошибка подтверждения Telegram. Попробуй ещё раз.',
  telegram_code_failed: 'Не удалось завершить вход. Попробуй ещё раз.',
  telegram_auth_not_configured: 'Telegram-авторизация не настроена.',
}

export default function AuthPage() {
  const [loading, setLoading] = useState(false)
  const [searchParams] = useSearchParams()

  const errorCode = searchParams.get('error')
  const errorMessage = errorCode
    ? (ERROR_MESSAGES[errorCode] ?? 'Что-то пошло не так. Попробуй ещё раз.')
    : null

  function handleClick() {
    setLoading(true)
    const botId = import.meta.env.VITE_TELEGRAM_BOT_ID
    if (botId) {
      const origin = window.location.origin
      const returnTo = `${origin}/api/v1/auth/telegram-callback`
      window.location.href =
        `https://oauth.telegram.org/auth` +
        `?bot_id=${encodeURIComponent(botId)}` +
        `&origin=${encodeURIComponent(origin)}` +
        `&return_to=${encodeURIComponent(returnTo)}`
    } else {
      window.location.href = '/api/v1/auth/telegram-dev-login'
    }
  }

  return (
    <div className={styles.page}>
      <div className={styles.container}>
        <div className={styles.ring} onClick={handleClick}>
          <CircularText
            text="АВТОРИЗОВАТЬСЯ В TELEGRAM • "
            radius={118}
            fontSize={13}
            spinDuration={14}
            onHover="speedUp"
            className={styles.circularText}
          />
          <div className={styles.iconCenter}>
            <TelegramIcon3D onClick={handleClick} />
          </div>
        </div>

        <motion.p
          className={styles.subtitle}
          animate={{ opacity: loading ? 0.4 : 1 }}
        >
          {loading ? 'переход в telegram…' : 'авторизоваться через telegram'}
        </motion.p>

        {errorMessage && (
          <motion.p
            className={styles.error}
            initial={{ opacity: 0, y: 4 }}
            animate={{ opacity: 1, y: 0 }}
          >
            {errorMessage}
          </motion.p>
        )}
      </div>
    </div>
  )
}
```

- [ ] **Шаг 2: Добавить стиль `.error` в `AuthPage.module.css`**

Открыть `web/src/pages/AuthPage.module.css`. Добавить в конец файла:

```css
.error {
  margin-top: 12px;
  color: var(--color-error, #e05252);
  font-size: 13px;
  text-align: center;
  max-width: 280px;
}
```

- [ ] **Шаг 3: Проверить TypeScript**

```bash
cd web
npx tsc --noEmit
```

Ожидаем: нет ошибок.

- [ ] **Шаг 4: Коммит**

```bash
git add src/pages/AuthPage.tsx src/pages/AuthPage.module.css
git commit -m "feat: implement telegram oauth button with dev-login and real widget support"
```

---

## Task 9: Проверка DEV flow (telegram-dev-login)

Финальная проверка без реального Telegram-бота.

- [ ] **Шаг 1: Убедиться что API запущен**

```bash
curl http://localhost:8000/api/v1/health
```

Ожидаем: `{"status":"ok"}`

- [ ] **Шаг 2: Убедиться что web запущен**

```bash
curl http://localhost:5173/api/v1/health
```

Ожидаем: `{"status":"ok"}` (через Vite proxy)

- [ ] **Шаг 3: Проверить dev-login flow в браузере**

1. Открыть `http://localhost:5173`
2. Должна появиться страница `/auth` с кнопкой Telegram
3. Нажать кнопку
4. Браузер сделает GET `/api/v1/auth/telegram-dev-login` → API редиректит на `/auth/callback?code=xxx`
5. `AuthCallbackPage` обменяет код → редирект на `/notes`
6. Должна открыться страница `/notes` (значит авторизация прошла)

- [ ] **Шаг 4: Проверить сохранение сессии при перезагрузке**

1. Находясь на `/notes`, нажать F5 (перезагрузка страницы)
2. Должны остаться на `/notes` (рефреш-кука присутствует → `/auth/refresh` вернёт токен)
3. Если редиректит на `/auth` — значит рефреш-кука не установилась. Проверить Network вкладку на шаге 3 — должен быть `Set-Cookie` в ответе на `/auth/telegram-dev-login`

- [ ] **Шаг 5: Проверить logout**

1. Найти кнопку logout в UI (если есть)
2. После logout — должен редиректить на `/auth`
3. При попытке вернуться на `/notes` — должен снова редиректить на `/auth`

---

## Task 10 (опционально): Настройка реального Telegram OAuth через ngrok

Выполнять только если нужно тестировать реальный Telegram Login Widget.

- [ ] **Шаг 1: Установить и запустить ngrok**

```bash
# Установка (macOS):
brew install ngrok
# или скачать с ngrok.com

ngrok http 5173
```

Получить URL вида `https://abc123.ngrok.io`.

- [ ] **Шаг 2: Узнать числовой Bot ID**

Бот-токен имеет вид `123456789:AAA...`. Числа до двоеточия — это Bot ID.

- [ ] **Шаг 3: Настроить домен бота в @BotFather**

В Telegram написать боту `@BotFather`:
```
/setdomain
```
Выбрать своего бота, ввести домен (БЕЗ `https://`, БЕЗ порта):
```
abc123.ngrok.io
```

- [ ] **Шаг 4: Обновить `api/.env`**

```env
TELEGRAM_LOGIN_REDIRECT_URL=https://abc123.ngrok.io/auth/callback
CORS_ALLOWED_ORIGINS=["https://abc123.ngrok.io"]
```

- [ ] **Шаг 5: Создать `web/.env.local`**

```bash
cd web
echo "VITE_TELEGRAM_BOT_ID=123456789" > .env.local
```

Заменить `123456789` на реальный Bot ID.

- [ ] **Шаг 6: Перезапустить оба сервиса**

```bash
# API:
docker compose -f docker-compose.yml -f docker-compose.dev.yml up --build

# Web (Ctrl+C и заново):
npm run dev
```

- [ ] **Шаг 7: Проверить реальный OAuth**

1. Открыть `https://abc123.ngrok.io` в браузере
2. Нажать кнопку Telegram
3. Должен открыться `oauth.telegram.org` с подтверждением входа
4. После подтверждения — редирект через API → `/auth/callback?code=xxx` → `/notes`
