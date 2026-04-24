# Frontend Auth Contract

Этот документ описывает, как React SPA должен работать с текущей авторизацией API.

## Общая модель

- `access_token` возвращается в JSON response
- `refresh_token` хранится только в `httpOnly` cookie
- frontend не читает `refresh_token` напрямую
- для защищённых ручек frontend отправляет:

```http
Authorization: Bearer <access_token>
```

- для работы refresh/logout браузер должен отправлять cookies

## Базовые правила для frontend

- использовать `credentials: "include"` для запросов, где нужен refresh cookie
- `access_token` хранить только в памяти приложения
- после перезагрузки страницы frontend должен пробовать `POST /auth/refresh`
- если refresh неуспешен, считать пользователя неавторизованным

## Формат ошибок

Все ошибки возвращаются в одном формате:

```json
{
  "error": {
    "code": "invalid_credentials",
    "message": "Invalid credentials.",
    "details": null
  }
}
```

Нужно ориентироваться в первую очередь на:
- HTTP status
- `error.code`

## Endpoints

### `POST /api/v1/auth/register`

Создаёт пользователя и сразу аутентифицирует его.

Request:

```json
{
  "email": "user@example.com",
  "display_name": "User",
  "password": "StrongPass123!"
}
```

Response `201`:

```json
{
  "user": {
    "id": "uuid",
    "email": "user@example.com",
    "display_name": "User",
    "is_active": true
  },
  "access_token": "jwt",
  "token_type": "bearer"
}
```

Errors:
- `409` / `email_already_registered`
- `422` / `validation_error`

### `POST /api/v1/auth/login`

Логин по email/password. Создаёт новую session.

Request:

```json
{
  "email": "user@example.com",
  "password": "StrongPass123!"
}
```

Response `200`:

```json
{
  "user": {
    "id": "uuid",
    "email": "user@example.com",
    "display_name": "User",
    "is_active": true
  },
  "access_token": "jwt",
  "token_type": "bearer"
}
```

Errors:
- `401` / `invalid_credentials`
- `422` / `validation_error`

### `POST /api/v1/auth/refresh`

Обновляет access token по refresh cookie. Ротирует refresh token.

Request body не нужен.

Требование:
- запрос должен идти с `credentials: "include"`

Response `200`:

```json
{
  "user": {
    "id": "uuid",
    "email": "user@example.com",
    "display_name": "User",
    "is_active": true
  },
  "access_token": "jwt",
  "token_type": "bearer"
}
```

Errors:
- `401` / `missing_refresh_token`
- `401` / `invalid_refresh_token`

### `POST /api/v1/auth/logout`

Выход из текущей session.

Требование:
- запрос должен идти с `credentials: "include"`

Response:
- `204 No Content`

### `GET /api/v1/auth/me`

Возвращает текущего пользователя по access token.

Headers:

```http
Authorization: Bearer <access_token>
```

Response `200`:

```json
{
  "id": "uuid",
  "email": "user@example.com",
  "display_name": "User",
  "is_active": true
}
```

Errors:
- `401` / `missing_access_token`
- `401` / `invalid_access_token`

## Session Management

### `GET /api/v1/auth/sessions`

Возвращает список активных сессий пользователя.

Headers:

```http
Authorization: Bearer <access_token>
```

Response `200`:

```json
[
  {
    "id": "session-id",
    "created_at": "2026-04-24T12:00:00+00:00",
    "last_used_at": "2026-04-24T12:30:00+00:00",
    "expires_at": "2026-05-24T12:00:00+00:00",
    "user_agent": "Mozilla/5.0 ...",
    "ip_address": "127.0.0.1",
    "is_current": true
  }
]
```

Errors:
- `401` / `missing_access_token`
- `401` / `invalid_access_token`

### `POST /api/v1/auth/logout-all`

Завершает все активные сессии пользователя.

Headers:

```http
Authorization: Bearer <access_token>
```

Также очищает refresh cookie.

Response:
- `204 No Content`

После этого текущий `access_token` тоже становится невалидным.

### `DELETE /api/v1/auth/sessions/{session_id}`

Завершает одну конкретную сессию пользователя.

Headers:

```http
Authorization: Bearer <access_token>
```

Response:
- `204 No Content`

Errors:
- `401` / `missing_access_token`
- `401` / `invalid_access_token`
- `404` / `session_not_found`

Если удаляется текущая session, refresh cookie тоже очищается.

## Recommended frontend flow

### App bootstrap

1. Старт приложения
2. `POST /auth/refresh` с `credentials: "include"`
3. Если `200`:
   - сохранить `access_token` в memory state
   - считать пользователя авторизованным
4. Если `401`:
   - считать пользователя неавторизованным

### Register

1. `POST /auth/register`
2. взять `access_token` из response
3. сохранить его в memory state
4. показать пользователя как logged-in

### Login

1. `POST /auth/login`
2. взять `access_token` из response
3. сохранить его в memory state
4. показать пользователя как logged-in

### Protected request

1. отправить запрос с `Authorization: Bearer <access_token>`
2. если backend вернул `401 invalid_access_token`
3. вызвать `POST /auth/refresh`
4. если refresh успешен:
   - заменить `access_token`
   - повторить исходный запрос один раз
5. если refresh неуспешен:
   - разлогинить пользователя

### Logout

1. `POST /auth/logout` с `credentials: "include"`
2. удалить `access_token` из memory state
3. очистить frontend auth state

## Что frontend не должен делать

- не хранить `refresh_token` в `localStorage`
- не пытаться читать refresh cookie из JS
- не использовать `access_token` как долгоживущий permanent token
- не ориентироваться только на текст `message`, если достаточно `error.code`
