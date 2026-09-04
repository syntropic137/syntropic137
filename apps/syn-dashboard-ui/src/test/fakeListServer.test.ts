/**
 * The double's own contract, because every wire assertion rests on it.
 *
 * The page tests now claim things like "the request carried page=2". That
 * claim is only worth anything if this endpoint reads the query string it was
 * actually sent and records it verbatim - a parser that quietly defaulted the
 * page would make all of them vacuous in the same way serving the `ListQuery`
 * object did (#1159).
 */

import { describe, expect, it } from 'vitest'

import { serveListEndpoint } from './fakeListServer'

const ROWS = [
  { status: 'completed', started_at: '2026-01-03T00:00:00Z', id: 'c' },
  { status: 'failed', started_at: '2026-01-02T00:00:00Z', id: 'b' },
  { status: 'completed', started_at: '2026-01-01T00:00:00Z', id: 'a' },
]

const server = serveListEndpoint({
  path: '/api/v1/things',
  collection: ROWS,
  matchesSearch: (row, term) => row.id === term,
})

async function get(query: string) {
  const response = await fetch(`/api/v1/things?${query}`)
  return response.json() as Promise<{
    things: typeof ROWS
    total: number
    status_counts: Record<string, number>
  }>
}

describe('serveListEndpoint', () => {
  it('pages from the query string, newest first', async () => {
    const body = await get('page=2&page_size=2')

    expect(body.things.map((row) => row.id)).toEqual(['a'])
    expect(body.total).toBe(3)
    expect(server.lastRequest.params.get('page')).toBe('2')
    expect(server.lastRequest.query.page).toBe(2)
  })

  it('records what arrived, not what was meant', async () => {
    await get('page=1&page_size=50&statuses=failed&q=b')

    const { params, query } = server.lastRequest
    expect(params.get('statuses')).toBe('failed')
    expect(query.statuses).toEqual(['failed'])
    expect(query.q).toBe('b')
    expect(server.requests).toHaveLength(1)
  })

  it('counts every status over the rows a query matches, ignoring the status filter', async () => {
    const body = await get('page=1&page_size=50&statuses=failed')

    expect(body.total).toBe(1)
    // An unselected chip still reports what selecting it would get.
    expect(body.status_counts).toEqual({ completed: 2, failed: 1 })
  })

  it('refuses a request with no page rather than inventing one', async () => {
    await expect(get('page_size=50')).rejects.toThrow(/missing page/)
    // Still recorded: a request that forgot its page IS the regression to
    // assert on, so the double must not swallow it.
    expect(server.requests).toHaveLength(1)
    expect(server.lastRequest.params.has('page')).toBe(false)
  })

  it('refuses a path it does not serve', async () => {
    await expect(fetch('/api/v1/elsewhere?page=1&page_size=50')).rejects.toThrow(
      /No fake endpoint/,
    )
  })
})
