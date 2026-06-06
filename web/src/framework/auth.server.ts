import type { AuthTokensResponse, UserResponse } from '../api/auth'

export interface ServerAuthBootstrap {
  user: UserResponse | null
  accessToken: string | null
  headers: Headers
}

const REFRESH_COOKIE_NAME = process.env.REFRESH_COOKIE_NAME ?? 'refresh_token'

export async function loadServerAuth(request: Request): Promise<ServerAuthBootstrap> {
  const headers = new Headers()
  const apiBaseUrl = process.env.SSR_API_BASE_URL ?? process.env.VITE_API_PROXY_TARGET
  const cookie = request.headers.get('cookie')

  if (!apiBaseUrl || !cookie?.includes(`${REFRESH_COOKIE_NAME}=`)) {
    return { user: null, accessToken: null, headers }
  }

  try {
    const response = await fetch(new URL('/api/v1/auth/bootstrap', apiBaseUrl), {
      method: 'GET',
      headers: {
        Accept: 'application/json',
        Cookie: cookie,
        ...(request.headers.get('user-agent')
          ? { 'User-Agent': request.headers.get('user-agent')! }
          : {}),
      },
    })

    if (!response.ok) return { user: null, accessToken: null, headers }

    const tokens = await response.json() as AuthTokensResponse
    return { user: tokens.user, accessToken: tokens.access_token, headers }
  } catch (error) {
    console.warn('[framework-ssr] auth bootstrap failed:', error)
    return { user: null, accessToken: null, headers }
  }
}
