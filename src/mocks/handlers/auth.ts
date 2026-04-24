import { http, HttpResponse } from 'msw'
import type { AuthTokensResponse } from '../../api/auth'

// Service worker module-level state — переживает навигацию, сбрасывается при закрытии вкладки
let mockAuthenticated = false

const MOCK_RESPONSE: AuthTokensResponse = {
  user: {
    id: 'tg-mock-1',
    email: '',
    display_name: 'Telegram User',
    is_active: true,
  },
  access_token: 'mock-access-token',
  token_type: 'bearer',
}
export const authHandlers = [
  // Dev-only: устанавливает флаг авторизации
  http.post('/api/v1/auth/mock-login', () => {
    mockAuthenticated = true
    return new HttpResponse(null, { status: 200 })
  }),

  // Bootstrap — проверяем флаг (не cookie, т.к. SW не видит заголовок Cookie)
  http.post('/api/v1/auth/refresh', () => {
    if (!mockAuthenticated) return new HttpResponse(null, { status: 401 })
    return HttpResponse.json<AuthTokensResponse>(MOCK_RESPONSE)
  }),

  // Logout — сбрасываем флаг
  http.post('/api/v1/auth/logout', () => {
    mockAuthenticated = false
    return new HttpResponse(null, { status: 200 })
  }),
]
