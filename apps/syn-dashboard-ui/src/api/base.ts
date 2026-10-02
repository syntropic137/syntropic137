export const API_BASE = '/api/v1'

/**
 * A non-2xx API response. Still an `Error` whose message is the server's
 * detail, so existing callers that only read `.message` are unaffected; callers
 * that must tell permission, expiry and other failures apart read `status` and
 * `code` (the structured detail's `code`, e.g. `cursor_expired`).
 */
export class ApiError extends Error {
  readonly status: number
  readonly code: string | null
  readonly detail: unknown

  constructor(status: number, detail: unknown) {
    super(ApiError.messageOf(status, detail))
    this.name = 'ApiError'
    this.status = status
    this.detail = detail
    this.code = ApiError.codeOf(detail)
  }

  private static messageOf(status: number, detail: unknown): string {
    if (typeof detail === 'string' && detail) return detail
    if (detail && typeof detail === 'object' && 'message' in detail && typeof detail.message === 'string') {
      return detail.message
    }
    return `API Error: ${status}`
  }

  private static codeOf(detail: unknown): string | null {
    if (detail && typeof detail === 'object' && 'code' in detail && typeof detail.code === 'string') return detail.code
    return null
  }
}

export async function fetchJSON<T>(url: string, options?: RequestInit): Promise<T> {
  const response = await fetch(url, {
    headers: {
      'Content-Type': 'application/json',
      ...options?.headers,
    },
    ...options,
  })

  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: response.statusText }))
    throw new ApiError(response.status, error?.detail)
  }

  return response.json()
}
