/**
 * A non-2xx API response. Still an `Error` whose message is the server's
 * detail; callers that must tell permission, expiry and other failures apart
 * read `status` and `code` (the structured detail's `code`, e.g.
 * `cursor_expired`). Ported from apps/syn-dashboard-ui/src/api/base.ts.
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

/** True for an AbortController cancellation, which callers should ignore. */
export function isAbortError(error: unknown): boolean {
  return (
    (typeof DOMException !== 'undefined' && error instanceof DOMException && error.name === 'AbortError') ||
    (error instanceof Error && error.name === 'AbortError')
  )
}

export function abortError(): Error {
  if (typeof DOMException !== 'undefined') return new DOMException('The operation was aborted.', 'AbortError')
  const e = new Error('The operation was aborted.')
  e.name = 'AbortError'
  return e
}
