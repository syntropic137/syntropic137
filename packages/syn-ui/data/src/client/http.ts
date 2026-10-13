import { clientConfig } from './config'
import { ApiError, abortError } from './errors'
import { Coalescer, flightTags } from './coalesce'
import { type QueryInit, toSearchParams } from './query'

export type HttpMethod = 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE'

export interface RequestOptions {
  method?: HttpMethod
  query?: QueryInit
  /** JSON-serialised. */
  body?: unknown
  signal?: AbortSignal
  cache?: RequestCache
  /** GETs are coalesced by URL (plus the cache epoch of a cache-managed signal) unless this is false. */
  coalesce?: boolean
}

const inflight = new Coalescer()

/**
 * The one request function every resource uses.
 *
 * `path` is relative to the API base ("/workflows/abc"). In fixtures mode the
 * request is answered by the fixtures router (loaded lazily, so it never
 * ships in a production first load).
 */
export function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const method = options.method ?? 'GET'
  const query = toSearchParams(options.query)
  const qs = query.toString()
  const config = clientConfig()

  if (config.fixtures) return fixtureRequest<T>(method, path, query, options)

  const url = `${config.baseUrl}${path}${qs ? `?${qs}` : ''}`
  const send = (signal?: AbortSignal) =>
    fetchJSON<T>(url, {
      method,
      signal,
      cache: options.cache,
      body: options.body === undefined ? undefined : JSON.stringify(options.body),
    })

  if (method === 'GET' && options.coalesce !== false) {
    const tag = options.signal ? flightTags.get(options.signal) : undefined
    return inflight.run(tag ? `${url}\u0000${tag}` : url, send, options.signal)
  }
  return send(options.signal)
}

export interface FormRequestOptions {
  method?: Extract<HttpMethod, 'POST' | 'PUT' | 'PATCH'>
  query?: QueryInit
  signal?: AbortSignal
}

/**
 * Multipart counterpart of request(): sends `form` as multipart/form-data
 * (the browser writes the boundary, so no Content-Type is set here) and
 * parses a JSON answer. Never coalesced. In fixtures mode the FormData is
 * handed to the fixture route as its body, unserialised.
 */
export function requestForm<T>(path: string, form: FormData, options: FormRequestOptions = {}): Promise<T> {
  const method = options.method ?? 'POST'
  const query = toSearchParams(options.query)
  const qs = query.toString()
  const config = clientConfig()
  if (config.fixtures) return fixtureRequest<T>(method, path, query, { body: form, signal: options.signal })
  return parseJSON<T>(config.fetch(`${config.baseUrl}${path}${qs ? `?${qs}` : ''}`, { method, body: form, signal: options.signal }))
}

/** Low-level JSON fetch with ApiError on non-2xx (React app's fetchJSON). */
export async function fetchJSON<T>(url: string, init: RequestInit = {}): Promise<T> {
  return parseJSON<T>(
    clientConfig().fetch(url, {
      ...init,
      headers: { 'Content-Type': 'application/json', ...init.headers },
    }),
  )
}

async function parseJSON<T>(pending: Promise<Response>): Promise<T> {
  const response = await pending
  if (!response.ok) {
    const error = (await response.json().catch(() => ({ detail: response.statusText }))) as { detail?: unknown } | null
    throw new ApiError(response.status, error?.detail)
  }
  if (response.status === 204) return undefined as T
  return (await response.json()) as T
}

async function fixtureRequest<T>(method: HttpMethod, path: string, query: URLSearchParams, options: RequestOptions): Promise<T> {
  const { resolveFixture } = await import('../fixtures/router')
  const latency = clientConfig().fixtureLatencyMs
  if (latency > 0) await delay(latency, options.signal)
  if (options.signal?.aborted) throw abortError()
  // Clone so a screen mutating a response never edits the fixture store.
  return structuredClone(await resolveFixture(method, path, query, options.body)) as T
}

function delay(ms: number, signal?: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    const t = setTimeout(resolve, ms)
    signal?.addEventListener(
      'abort',
      () => {
        clearTimeout(t)
        reject(abortError())
      },
      { once: true },
    )
  })
}
