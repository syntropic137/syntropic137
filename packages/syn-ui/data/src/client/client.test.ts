import { afterEach, describe, expect, it, vi } from 'vitest'
import { ApiError, Coalescer, configureClient, isAbortError, listQueryParams, mapLimit, request, toSearchParams, withQuery } from './index'

const realFetch = globalThis.fetch
afterEach(() => {
  configureClient({ fixtures: false, baseUrl: '/api/v1', fetch: (...a) => realFetch(...a) })
})

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })

describe('query params', () => {
  it('drops empty values and joins arrays', () => {
    expect(toSearchParams({ a: 1, b: '', c: null, d: undefined, e: ['x', 'y'], f: [], g: false }).toString()).toBe('a=1&e=x%2Cy&g=false')
    expect(withQuery('/w', { page: 2 })).toBe('/w?page=2')
    expect(withQuery('/w', {})).toBe('/w')
  })
  it('serialises the shared list query', () => {
    const p = listQueryParams({ page: 2, page_size: 25, statuses: ['failed', 'cancelled'], started_after: '2026-10-01T00:00:00Z', q: 'pr' })
    expect(p.toString()).toBe('page=2&page_size=25&statuses=failed%2Ccancelled&started_after=2026-10-01T00%3A00%3A00Z&q=pr')
    expect(listQueryParams({ page: 1, page_size: 10, started_after: 'x' }, 'created').get('created_after')).toBe('x')
  })
})

describe('request', () => {
  it('prefixes the base URL and parses JSON', async () => {
    const fetch = vi.fn(async () => json({ ok: true }))
    configureClient({ fetch, baseUrl: '/api/v1' })
    await expect(request('/workflows', { query: { page: 2 } })).resolves.toEqual({ ok: true })
    expect(fetch).toHaveBeenCalledWith('/api/v1/workflows?page=2', expect.objectContaining({ method: 'GET' }))
  })
  it('throws ApiError with status, message and code', async () => {
    configureClient({ fetch: async () => json({ detail: { message: 'Cursor expired', code: 'cursor_expired' } }, 410) })
    const err = await request('/x').catch((e: unknown) => e)
    expect(err).toBeInstanceOf(ApiError)
    expect(err).toMatchObject({ status: 410, code: 'cursor_expired', message: 'Cursor expired' })
  })
  it('sends JSON bodies for mutations and never coalesces them', async () => {
    const fetch = vi.fn(async () => json({}))
    configureClient({ fetch })
    await Promise.all([request('/t', { method: 'POST', body: { a: 1 } }), request('/t', { method: 'POST', body: { a: 1 } })])
    expect(fetch).toHaveBeenCalledTimes(2)
    expect(fetch.mock.calls[0]).toEqual(['/api/v1/t', expect.objectContaining({ method: 'POST', body: '{"a":1}' })])
  })
  it('coalesces concurrent identical GETs', async () => {
    const fetch = vi.fn(async () => json({ n: 1 }))
    configureClient({ fetch })
    const [a, b] = await Promise.all([request('/same'), request('/same')])
    expect(a).toEqual(b)
    expect(fetch).toHaveBeenCalledTimes(1)
  })
})

describe('Coalescer', () => {
  it('aborting one waiter leaves the other served', async () => {
    const c = new Coalescer()
    let resolve!: (v: number) => void
    let underlying: AbortSignal | undefined
    const start = (signal: AbortSignal) => {
      underlying = signal
      return new Promise<number>((r) => (resolve = r))
    }
    const a = new AbortController()
    const p1 = c.run('k', start, a.signal)
    const p2 = c.run('k', start, new AbortController().signal)
    a.abort()
    await expect(p1).rejects.toSatisfy(isAbortError)
    expect(underlying?.aborted).toBe(false)
    resolve(7)
    await expect(p2).resolves.toBe(7)
    expect(c.size).toBe(0)
  })
  it('aborts the shared request when every waiter leaves', async () => {
    const c = new Coalescer()
    let underlying: AbortSignal | undefined
    const start = (signal: AbortSignal) => {
      underlying = signal
      return new Promise<number>(() => {})
    }
    const a = new AbortController()
    const b = new AbortController()
    const p1 = c.run('k', start, a.signal).catch(() => 'aborted')
    const p2 = c.run('k', start, b.signal).catch(() => 'aborted')
    a.abort()
    b.abort()
    expect(await Promise.all([p1, p2])).toEqual(['aborted', 'aborted'])
    expect(underlying?.aborted).toBe(true)
    expect(c.size).toBe(0)
  })
  it('rejects immediately for an already-aborted signal', async () => {
    const c = new Coalescer()
    const a = new AbortController()
    a.abort()
    await expect(c.run('k', async () => 1, a.signal)).rejects.toSatisfy(isAbortError)
  })
})

describe('mapLimit', () => {
  it('keeps order and caps concurrency', async () => {
    let live = 0
    let peak = 0
    const out = await mapLimit([5, 1, 3, 2], 2, async (v) => {
      live++
      peak = Math.max(peak, live)
      await new Promise((r) => setTimeout(r, v))
      live--
      return v * 10
    })
    expect(out).toEqual([50, 10, 30, 20])
    expect(peak).toBe(2)
  })
})
