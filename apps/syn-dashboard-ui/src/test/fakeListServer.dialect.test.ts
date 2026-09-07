/**
 * The artifacts spelling of the double's contract.
 *
 * Its own file because `serveListEndpoint` installs one `fetch` per test file:
 * a second endpoint declared beside the first would silently replace it, and
 * the replaced one's assertions would be the vacuous kind this whole approach
 * exists to avoid.
 *
 * Everything the artifact hook tests claim about a window, a type filter or a
 * tally rests on these five behaviours being the artifacts spelling rather
 * than the executions one.
 */

import { describe, expect, it } from 'vitest'

import { ARTIFACT_DIALECT, serveListEndpoint } from './fakeListServer'

const ROWS = [
  { artifact_type: 'report', created_at: '2026-01-03T00:00:00Z', id: 'c' },
  { artifact_type: 'log', created_at: '2026-01-02T00:00:00Z', id: 'b' },
  { artifact_type: 'report', created_at: '2026-01-01T00:00:00Z', id: 'a' },
]

const server = serveListEndpoint({
  path: '/api/v1/artifacts',
  collection: ROWS,
  matchesSearch: (row, term) => row.id === term,
  dialect: ARTIFACT_DIALECT,
})

async function get(query: string) {
  const response = await fetch(`/api/v1/artifacts?${query}`)
  return response.json() as Promise<{
    artifacts: typeof ROWS
    total: number
    type_counts: Record<string, number>
  }>
}

describe('serveListEndpoint, artifacts dialect', () => {
  it('pages newest-first by when the artifact was created', async () => {
    const body = await get('page=2&page_size=2')

    expect(body.artifacts.map((row) => row.id)).toEqual(['a'])
    expect(body.total).toBe(3)
  })

  it('bounds the window on created_at, and ignores a started_at bound', async () => {
    const bounded = await get('page=1&page_size=50&created_after=2026-01-02T00:00:00Z')
    expect(bounded.artifacts.map((row) => row.id)).toEqual(['c', 'b'])
    expect(bounded.total).toBe(2)
    expect(server.lastRequest.query.started_after).toBe('2026-01-02T00:00:00Z')

    // `started_after` is not this endpoint's parameter: sending it must not
    // narrow anything, or a hook that used the wrong one would look correct.
    const unbounded = await get('page=1&page_size=50&started_after=2026-01-02T00:00:00Z')
    expect(unbounded.total).toBe(3)
  })

  it('tallies by type, under the key this endpoint answers with', async () => {
    const body = await get('page=1&page_size=50')

    expect(body.type_counts).toEqual({ report: 2, log: 1 })
    expect(body).not.toHaveProperty('status_counts')
  })

  it('narrows by artifact_type while still tallying every type', async () => {
    const body = await get('page=1&page_size=50&artifact_type=log')

    expect(body.artifacts.map((row) => row.id)).toEqual(['b'])
    expect(body.total).toBe(1)
    // An unselected type still reports what selecting it would get.
    expect(body.type_counts).toEqual({ report: 2, log: 1 })
  })

  it('records what arrived, as it arrived', async () => {
    await get('page=1&page_size=10&artifact_type=report&q=a')

    const { params, query } = server.lastRequest
    expect(params.get('artifact_type')).toBe('report')
    expect(query.page_size).toBe(10)
    expect(query.q).toBe('a')
  })
})
