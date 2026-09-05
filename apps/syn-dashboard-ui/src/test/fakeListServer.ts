/**
 * A list endpoint, served over `fetch`, that answers the query string it is
 * actually sent - and remembers every request it received.
 *
 * The point of the paging work is that the browser stops deciding which rows
 * match; the server does. Two things have to be true for a test to show that,
 * and the first one alone is not enough:
 *
 *   1. The double must really filter, tally, order and slice from the query,
 *      so a hook that forgets to forward a filter gets a visibly wrong answer
 *      rather than the same canned array either way.
 *   2. The double must be reached the way the server is reached - through
 *      `fetch`, from a URL the page built - so the serialisation hop runs.
 *
 * Serving the `ListQuery` OBJECT instead was the gap this closes. It left
 * `listQueryParams` unexecuted, and a mutation that forced `page=1` onto every
 * outgoing request passed the whole suite: nothing observed a request, only
 * the argument to the function that would have built one.
 *
 * So this installs itself over `globalThis.fetch`, parses the query string
 * back into a query the way the API does, and records what arrived. Assert
 * against `requests` and you are asserting on the wire.
 *
 * Mirrors `syn_domain.pagination.paginate`:
 *   - `total` counts rows matching EVERY filter, including status
 *   - `status_counts` tallies the same rows IGNORING the status filter, so an
 *     unselected chip still reports what selecting it would get
 *   - rows are ordered newest-first and sliced to the requested page
 */

import { afterEach, beforeEach, vi } from 'vitest'

import type { ListQuery } from '../api/listQuery'

export interface ListRow {
  status: string
  started_at: string
}

/** One request the page really issued, as it arrived at the endpoint. */
export interface RecordedRequest {
  /** The URL the page asked for, query string and all. */
  url: string
  /** Its parameters verbatim - what is on the wire, not what was meant. */
  params: URLSearchParams
  /** Those parameters read back the way the API reads them. */
  query: ListQuery
}

export interface FakeListServer {
  /** Every request to this endpoint since the current test began, in order. */
  readonly requests: readonly RecordedRequest[]
  /** The most recent request. Throws if the page has issued none. */
  readonly lastRequest: RecordedRequest
}

export interface ServeListOptions<TRow extends ListRow> {
  /** Path this endpoint answers, e.g. `/api/v1/executions`. */
  path: string
  /** The whole collection. The endpoint decides which of it any query gets. */
  collection: readonly TRow[]
  /** How `q` matches a row; the real server picks the fields, so this does. */
  matchesSearch?: (row: TRow, term: string) => boolean
}

/**
 * Serve `path` from `collection` for every test in the calling file.
 *
 * Call it once at module scope: it installs the endpoint before each test and
 * removes it after, so a caller never handles the lifecycle or the recording.
 *
 * ```ts
 * const server = serveListEndpoint({ path: '/api/v1/sessions', collection: SESSIONS })
 * // ...then, in a test:
 * expect(server.lastRequest.params.get('page')).toBe('2')
 * ```
 */
export function serveListEndpoint<TRow extends ListRow>({
  path,
  collection,
  matchesSearch,
}: ServeListOptions<TRow>): FakeListServer {
  // Both endpoints name the row array after the resource in their path, which
  // is the whole of what differs between the two envelopes. Settled here, so a
  // path that is not a list endpoint fails at setup rather than mid-test.
  const rowsKey = path.split('/').filter(Boolean).at(-1)
  if (!rowsKey) throw new Error(`Not a list endpoint path: ${path}`)

  const requests: RecordedRequest[] = []

  beforeEach(() => {
    requests.length = 0
    // Async, like the real thing: everything below reaches a caller as a
    // rejected promise rather than as a synchronous throw.
    vi.stubGlobal('fetch', async (input: RequestInfo | URL): Promise<Response> => {
      const url = requestUrl(input)
      const { pathname, searchParams } = new URL(url, 'http://dashboard.test')
      if (pathname !== path) {
        throw new Error(`No fake endpoint for ${url}; this test serves ${path} only`)
      }
      // Recorded before it is read, and read lazily, so that a request missing
      // a required parameter is still visible to assert on: that request IS
      // the regression, and a double that dropped it would hide it.
      const request: RecordedRequest = {
        url,
        params: searchParams,
        get query() {
          return readQuery(searchParams)
        },
      }
      requests.push(request)
      return answer(rowsKey, collection, request.query, matchesSearch)
    })
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  return {
    get requests() {
      return requests
    },
    get lastRequest() {
      const last = requests.at(-1)
      if (!last) throw new Error(`No request reached ${path}`)
      return last
    },
  }
}

function requestUrl(input: RequestInfo | URL): string {
  if (typeof input === 'string') return input
  if (input instanceof URL) return input.href
  return input.url
}

/**
 * Read a query string the way the API reads it.
 *
 * Written from the parameter names rather than by inverting `listQueryParams`,
 * because a parser derived from the serialiser agrees with it however wrong
 * both are. This is the wire contract stated a second time, independently.
 *
 * `page` and `page_size` are required, as they are on the API, so a request
 * that omits one fails here rather than quietly paging from nowhere.
 */
function readQuery(params: URLSearchParams): ListQuery {
  const statuses = params.get('statuses')
  return {
    page: requiredNumber(params, 'page'),
    page_size: requiredNumber(params, 'page_size'),
    statuses: statuses ? statuses.split(',') : undefined,
    started_after: params.get('started_after') ?? undefined,
    started_before: params.get('started_before') ?? undefined,
    q: params.get('q') ?? undefined,
  }
}

function requiredNumber(params: URLSearchParams, name: string): number {
  const raw = params.get(name)
  const value = raw === null ? NaN : Number(raw)
  if (!Number.isFinite(value)) {
    throw new Error(`Request is missing ${name}: ?${params}`)
  }
  return value
}

function answer<TRow extends ListRow>(
  rowsKey: string,
  collection: readonly TRow[],
  query: ListQuery,
  matchesSearch: ((row: TRow, term: string) => boolean) | undefined,
): Response {
  const beforeStatus = collection.filter(
    (row) =>
      (!query.started_after || row.started_at >= query.started_after) &&
      (!query.started_before || row.started_at <= query.started_before) &&
      (!query.q || (matchesSearch?.(row, query.q) ?? true)),
  )

  const status_counts: Record<string, number> = {}
  for (const row of beforeStatus) {
    status_counts[row.status] = (status_counts[row.status] ?? 0) + 1
  }

  const allowed = query.statuses
  const matched = allowed?.length
    ? beforeStatus.filter((row) => allowed.includes(row.status))
    : beforeStatus

  const ordered = [...matched].sort((a, b) => b.started_at.localeCompare(a.started_at))
  const offset = (query.page - 1) * query.page_size

  return new Response(
    JSON.stringify({
      [rowsKey]: ordered.slice(offset, offset + query.page_size),
      total: matched.length,
      page: query.page,
      page_size: query.page_size,
      status_counts,
    }),
    { status: 200, headers: { 'Content-Type': 'application/json' } },
  )
}
