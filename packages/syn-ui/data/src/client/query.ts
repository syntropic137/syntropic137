/** A value a query parameter may take. Arrays are joined with commas; null/undefined/'' are dropped. */
export type QueryValue = string | number | boolean | null | undefined | readonly string[]
export type QueryInit = URLSearchParams | Record<string, QueryValue>

/** Build URLSearchParams, skipping empty values (the API refuses undeclared params, #1313). */
export function toSearchParams(init: QueryInit | undefined): URLSearchParams {
  if (!init) return new URLSearchParams()
  if (init instanceof URLSearchParams) return new URLSearchParams(init)
  const params = new URLSearchParams()
  for (const [key, value] of Object.entries(init)) {
    if (value === null || value === undefined || value === '') continue
    if (Array.isArray(value)) {
      if (value.length > 0) params.set(key, value.join(','))
    } else {
      params.set(key, String(value))
    }
  }
  return params
}

/** "/workflows" + params -> "/workflows?page=2" (no "?" when empty). */
export function withQuery(path: string, init?: QueryInit): string {
  const qs = toSearchParams(init).toString()
  return qs ? `${path}?${qs}` : path
}

/** Encode one path segment. */
export const seg = (value: string): string => encodeURIComponent(value)
