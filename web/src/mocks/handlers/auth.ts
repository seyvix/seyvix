import { http, HttpResponse } from 'msw'

const mockUser = {
  id: 'mock-user',
  telegram_id: '1000001',
  telegram_username: 'hardzz',
  telegram_photo_url: null,
  avatar_url: null,
  display_name: 'lv',
  is_active: true,
}

const tokenResponse = {
  user: mockUser,
  access_token: 'mock-access-token',
  token_type: 'bearer',
}

export const authHandlers = [
  http.post('/api/v1/auth/refresh', () => HttpResponse.json(tokenResponse)),
  http.post('/api/v1/auth/login', () => HttpResponse.json(tokenResponse)),
  http.post('/api/v1/auth/register', () => HttpResponse.json(tokenResponse)),
  http.post('/api/v1/auth/telegram-web-app', () => HttpResponse.json(tokenResponse)),
  http.post('/api/v1/auth/telegram-result', () => HttpResponse.json(tokenResponse)),
  http.post('/api/v1/auth/telegram-oidc-code', () => HttpResponse.json(tokenResponse)),
  http.post('/api/v1/auth/telegram-code', () => HttpResponse.json(tokenResponse)),
  http.post('/api/v1/auth/logout', () => HttpResponse.json({ ok: true })),
  http.get('/api/v1/auth/sessions', () => HttpResponse.json([])),
]
