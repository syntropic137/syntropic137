import { afterEach, describe, expect, it, vi } from 'vitest'
import { MAX_PAGE_SIZE, configureClient } from '../client'
import { listAllEvals } from './evals'

const realFetch = globalThis.fetch
afterEach(() => {
  configureClient({ fixtures: false, fixtureLatencyMs: 120, fetch: (...a) => realFetch(...a) })
})

/** GET /evals as the API answers it: 422 above MAX_PAGE_SIZE, otherwise one page of `total` rows. */
function evalsApi(total: number) {
  return vi.fn(async (input: RequestInfo | URL) => {
    const url = new URL(String(input), 'http://x')
    const page = Number(url.searchParams.get('page') ?? '1')
    const size = Number(url.searchParams.get('page_size') ?? '20')
    if (size > MAX_PAGE_SIZE) return new Response(JSON.stringify({ detail: 'page_size too large' }), { status: 422 })
    const from = (page - 1) * size
    const evals = Array.from({ length: Math.max(0, Math.min(size, total - from)) }, (_, i) => ({ eval_id: `eval-${from + i}` }))
    return new Response(JSON.stringify({ evals, total, page, page_size: size, status_counts: {} }), { status: 200, headers: { 'Content-Type': 'application/json' } })
  })
}

describe('listAllEvals (parity-2 #2: the list stopped at 100 of 107)', () => {
  it('reads every page, never above MAX_PAGE_SIZE, and keeps the API total', async () => {
    const fetch = evalsApi(107)
    configureClient({ fetch, baseUrl: '/api/v1' })
    const res = await listAllEvals()
    expect(res.total).toBe(107)
    expect(res.evals).toHaveLength(107)
    expect(new Set(res.evals.map((e) => e.eval_id)).size).toBe(107)
    expect(fetch).toHaveBeenCalledTimes(2)
  })

  it('stops after one request when the first page holds them all', async () => {
    const fetch = evalsApi(42)
    configureClient({ fetch, baseUrl: '/api/v1' })
    const res = await listAllEvals({ tag: 'case:x' })
    expect(res.evals).toHaveLength(42)
    expect(fetch).toHaveBeenCalledTimes(1)
    expect(String(fetch.mock.calls[0]![0])).toContain('tag=case%3Ax')
  })
})
