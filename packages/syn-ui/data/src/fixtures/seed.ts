import { ApiError } from '../client/errors'
import { MAX_PAGE_SIZE } from '../client/listQuery'
/**
 * Shared helpers for fixture data. Sample values come from the design canvas
 * boards (names, durations, token counts, costs) so screens rendered on
 * fixtures look like the boards.
 *
 * All timestamps are relative to FIXTURE_NOW so the data is deterministic.
 */
export const FIXTURE_NOW = Date.UTC(2026, 9, 8, 9, 0, 0)

export const MINUTE = 60_000
export const HOUR = 60 * MINUTE
export const DAY = 24 * HOUR
export const WEEK = 7 * DAY

/** ISO timestamp `ms` before FIXTURE_NOW. */
export function ago(ms: number): string {
  return new Date(FIXTURE_NOW - ms).toISOString()
}

/** ISO timestamp `ms` after `iso`. */
export function after(iso: string, ms: number): string {
  return new Date(Date.parse(iso) + ms).toISOString()
}

export const REPO_SYN = 'https://github.com/syntropic137/syntropic137'
export const REPO_SANDBOX = 'https://github.com/syntropic137/sandbox_syn-engineer-beta'

/** "2026-10-08T09:00:00.000Z" -> stable hex id from a seed string. */
export function fakeId(seed: string, length = 12): string {
  let h1 = 0x811c9dc5
  let h2 = 0x01000193
  for (let i = 0; i < seed.length; i++) {
    const c = seed.charCodeAt(i)
    h1 = Math.imul(h1 ^ c, 16777619) >>> 0
    h2 = Math.imul(h2 ^ c, 2246822519) >>> 0
  }
  return (h1.toString(16).padStart(8, '0') + h2.toString(16).padStart(8, '0') + h1.toString(16)).slice(0, length)
}

export interface Page<T> {
  rows: T[]
  total: number
  page: number
  page_size: number
}

/** Apply `page`/`page_size` query params (defaults 1 and `defaultSize`). */
export function paginate<T>(rows: readonly T[], query: URLSearchParams, defaultSize = 50): Page<T> {
  const page = Math.max(1, Number(query.get('page') ?? 1) || 1)
  const page_size = Math.max(1, Number(query.get('page_size') ?? defaultSize) || defaultSize)
  if (page_size > MAX_PAGE_SIZE) {
    // Same shape and status as the API's validation error, so a route that
    // over-asks breaks in fixtures mode exactly as it does against a server.
    throw new ApiError(422, [{ loc: ['query', 'page_size'], msg: `Input should be less than or equal to ${MAX_PAGE_SIZE}`, type: 'less_than_equal' }])
  }
  const start = (page - 1) * page_size
  return { rows: rows.slice(start, start + page_size), total: rows.length, page, page_size }
}

/** Tally rows by a key. */
export function countBy<T>(rows: readonly T[], key: (row: T) => string): Record<string, number> {
  const out: Record<string, number> = {}
  for (const r of rows) out[key(r)] = (out[key(r)] ?? 0) + 1
  return out
}

/** The `statuses` (comma list) and `q` filters the list endpoints share. */
export function filterList<T>(rows: readonly T[], query: URLSearchParams, status: (r: T) => string, text: (r: T) => string): T[] {
  const statuses = query.get('statuses')?.split(',').filter(Boolean) ?? []
  const q = query.get('q')?.toLowerCase() ?? ''
  return rows.filter((r) => (statuses.length === 0 || statuses.includes(status(r))) && (!q || text(r).toLowerCase().includes(q)))
}

/** "$0.33" style display string the API sends in *_display fields. */
export function costDisplay(usd: number): string {
  return `$${usd.toFixed(2)}`
}

/** "261.7K" style display string the API sends in *_display fields. */
export function tokensDisplay(n: number): string {
  if (n >= 1e6) return `${(n / 1e6).toFixed(1)}M`
  if (n >= 1e3) return `${(n / 1e3).toFixed(1)}K`
  return String(n)
}

/** "3m 47s" style display string the API sends in *_display fields. */
export function durationDisplay(seconds: number | null): string {
  if (seconds === null) return '—'
  if (seconds < 60) return `${Math.round(seconds)}s`
  const m = Math.floor(seconds / 60)
  const s = Math.round(seconds % 60)
  return s ? `${m}m ${s}s` : `${m}m`
}
