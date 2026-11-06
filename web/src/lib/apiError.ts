/**
 * Typed HTTP error for every backend call.
 *
 * The backend reports failures as `{"error": {"code", "message", "details"}}`; older/other
 * endpoints may use `{"message"}` or FastAPI's `{"detail"}`. `message` is user-readable when the
 * backend provided one, otherwise the caller's fallback.
 */
export class ApiError extends Error {
  readonly status: number
  readonly code: string
  readonly details: unknown

  constructor(status: number, code: string, message: string, details: unknown = null) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.code = code
    this.details = details
  }
}

/** 4xx responses are deterministic: retrying them only wastes requests. */
export function isClientError(error: unknown): boolean {
  return error instanceof ApiError && error.status >= 400 && error.status < 500
}

interface ErrorBody {
  error?: { code?: unknown; message?: unknown; details?: unknown }
  code?: unknown
  message?: unknown
  detail?: unknown
}

function asString(value: unknown): string | null {
  return typeof value === 'string' && value.trim() ? value : null
}

export async function toApiError(res: Response, fallbackMessage: string): Promise<ApiError> {
  let body: ErrorBody | null = null
  try {
    body = (await res.json()) as ErrorBody
  } catch {
    body = null
  }
  const envelope: { code?: unknown; message?: unknown; details?: unknown } | null =
    body?.error ?? body
  const code = asString(envelope?.code) ?? `http_${res.status}`
  const message = asString(envelope?.message) ?? asString(body?.detail) ?? fallbackMessage
  return new ApiError(res.status, code, message, envelope?.details ?? null)
}

/** Throws an `ApiError` unless the response is 2xx. */
export async function ensureOk(res: Response, fallbackMessage: string): Promise<Response> {
  if (!res.ok) throw await toApiError(res, fallbackMessage)
  return res
}

export async function readJson<T>(res: Response, fallbackMessage: string): Promise<T> {
  await ensureOk(res, fallbackMessage)
  return (await res.json()) as T
}

export interface AccessDeniedInfo {
  message: string
  telegramUserId: number | null
  username: string | null
}

/** Extracts the allowlist denial (`403 access_denied`) payload, if that is what `error` is. */
export function accessDeniedInfo(error: unknown): AccessDeniedInfo | null {
  if (!(error instanceof ApiError) || error.status !== 403 || error.code !== 'access_denied') {
    return null
  }
  const first = Array.isArray(error.details) ? error.details[0] as Record<string, unknown> | undefined : undefined
  const rawId = first?.telegram_user_id
  const telegramUserId = typeof rawId === 'number'
    ? rawId
    : typeof rawId === 'string' && /^\d+$/.test(rawId) ? Number(rawId) : null
  return {
    message: error.message,
    telegramUserId,
    username: asString(first?.username),
  }
}
