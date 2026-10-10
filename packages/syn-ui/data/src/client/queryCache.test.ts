import { describe, expect, it, vi } from 'vitest'
import { isAbortError } from './errors'
import { QueryCache, STALE_AFTER, queryKey } from './queryCache'

function setup(fixtures = false) {
  let now = 1_000
  const cache = new QueryCache({ now: () => now, fixtures: () => fixtures })
  return { cache, advance: (ms: number) => (now += ms) }
}

/** A fetcher whose calls resolve when told to. */
function deferred<T>() {
  const calls: Array<{ resolve: (v: T) => void; reject: (e: unknown) => void; signal: AbortSignal }> = []
  const fetcher = vi.fn((signal: AbortSignal) => new Promise<T>((resolve, reject) => calls.push({ resolve, reject, signal })))
  return { fetcher, calls }
}

const flush = () => new Promise((r) => setTimeout(r, 0))

describe('queryKey', () => {
  it('normalises object key order, undefined fields and URLSearchParams', () => {
    expect(queryKey('listExecutions', [{ page: 1, q: undefined, page_size: 50 }])).toBe(queryKey('listExecutions', [{ page_size: 50, page: 1 }]))
    expect(queryKey('a', [new URLSearchParams('b=2&a=1')])).toBe(queryKey('a', [new URLSearchParams('a=1&b=2')]))
    expect(queryKey('getExecution', ['x'])).not.toBe(queryKey('getExecution', ['y']))
    expect(queryKey('getExecution', ['x'])).not.toBe(queryKey('getSession', ['x']))
    expect(queryKey('a', [undefined])).not.toBe(queryKey('a', [null]))
  })

  it('tags types and encodes pairs as tuples, so different requests never share a key', () => {
    // Each pair below printed the same under the old string encoding.
    expect(queryKey('a', [new URLSearchParams([['a=b', 'c']])])).not.toBe(queryKey('a', [new URLSearchParams([['a', 'b=c']])]))
    expect(queryKey('a', [new URLSearchParams('a=1')])).not.toBe(queryKey('a', [['a=1']]))
    expect(queryKey('a', [undefined])).not.toBe(queryKey('a', [null]))
    expect(queryKey('a', ['1'])).not.toBe(queryKey('a', [1]))
    expect(queryKey('a', [{ k: 'v' }])).not.toBe(queryKey('a', [[['k', 'v']]]))
  })
})

describe('QueryCache', () => {
  it('serves fresh data without a request', async () => {
    const { cache, advance } = setup()
    const fetcher = vi.fn(async () => 1)
    await expect(cache.get('getExecution', ['e'], fetcher)).resolves.toBe(1)
    advance(STALE_AFTER.detail - 1)
    await expect(cache.get('getExecution', ['e'], fetcher)).resolves.toBe(1)
    expect(fetcher).toHaveBeenCalledTimes(1)
    expect(cache.peek('getExecution', ['e'])).toBe(1)
  })

  it('serves stale data at once, refreshes in the background and notifies', async () => {
    const { cache, advance } = setup()
    let n = 0
    const fetcher = vi.fn(async () => ++n)
    await cache.get('listExecutions', [{}], fetcher, { staleAfter: 'list' })
    const heard = vi.fn()
    cache.subscribe([queryKey('listExecutions', [{}])], heard)
    advance(STALE_AFTER.list)
    await expect(cache.get('listExecutions', [{}], fetcher, { staleAfter: 'list' })).resolves.toBe(1)
    await flush()
    expect(fetcher).toHaveBeenCalledTimes(2)
    expect(heard).toHaveBeenCalledTimes(1)
    await expect(cache.get('listExecutions', [{}], fetcher, { staleAfter: 'list' })).resolves.toBe(2)
  })

  it('honours a per-call staleAfter in ms', async () => {
    const { cache, advance } = setup()
    const fetcher = vi.fn(async () => 1)
    await cache.get('getMetrics', [], fetcher, { staleAfter: 10 })
    advance(10)
    await cache.get('getMetrics', [], fetcher, { staleAfter: 10 })
    expect(fetcher).toHaveBeenCalledTimes(2)
  })

  it('de-duplicates concurrent loads and lets one caller abort alone', async () => {
    const { cache } = setup()
    const d = deferred<number>()
    const a = new AbortController()
    const p1 = cache.get('getSession', ['s'], d.fetcher, { signal: a.signal })
    const p2 = cache.get('getSession', ['s'], d.fetcher, { signal: new AbortController().signal })
    expect(d.fetcher).toHaveBeenCalledTimes(1)
    a.abort()
    await expect(p1).rejects.toSatisfy(isAbortError)
    expect(d.calls[0]!.signal.aborted).toBe(false)
    d.calls[0]!.resolve(5)
    await expect(p2).resolves.toBe(5)
  })

  it('aborts the shared load when every caller leaves, and stores nothing', async () => {
    const { cache } = setup()
    const d = deferred<number>()
    const a = new AbortController()
    const p = cache.get('getSession', ['s'], d.fetcher, { signal: a.signal }).catch((e: unknown) => e)
    a.abort()
    expect(isAbortError(await p)).toBe(true)
    expect(d.calls[0]!.signal.aborted).toBe(true)
    expect(cache.peek('getSession', ['s'])).toBeUndefined()
  })

  it('does not cache failures', async () => {
    const { cache } = setup()
    const fetcher = vi.fn().mockRejectedValueOnce(new Error('boom')).mockResolvedValueOnce(2)
    await expect(cache.get('getEval', ['x'], fetcher)).rejects.toThrow('boom')
    await expect(cache.get('getEval', ['x'], fetcher)).resolves.toBe(2)
  })

  it('invalidate by key or predicate marks stale and notifies listeners', async () => {
    const { cache } = setup()
    let n = 0
    const fetcher = async () => ++n
    await cache.get('getExecution', ['a'], fetcher)
    await cache.get('getExecution', ['b'], fetcher)
    const heardA = vi.fn()
    const heardB = vi.fn()
    cache.subscribe([queryKey('getExecution', ['a'])], heardA)
    const offB = cache.subscribe([queryKey('getExecution', ['b'])], heardB)
    expect(cache.invalidate(queryKey('getExecution', ['a']))).toBe(1)
    expect(heardA).toHaveBeenCalledTimes(1)
    expect(heardB).not.toHaveBeenCalled()
    // invalidated: the next read waits for the refresh rather than serving the old value
    await expect(cache.get('getExecution', ['a'], fetcher)).resolves.toBe(3)
    expect(cache.peek('getExecution', ['a'])).toBe(3)
    offB()
    expect(cache.invalidate((e) => e.name === 'getExecution')).toBe(2)
    expect(heardB).not.toHaveBeenCalled()
  })

  it('never stores a load that started before an invalidation', async () => {
    const { cache } = setup()
    const d = deferred<number>()
    const p = cache.get('getExecution', ['a'], d.fetcher)
    cache.invalidate(queryKey('getExecution', ['a']))
    d.calls[0]!.resolve(1)
    await expect(p).resolves.toBe(1) // its own caller still gets it
    expect(cache.peek('getExecution', ['a'])).toBeUndefined()
    const next = vi.fn(async () => 2)
    await expect(cache.get('getExecution', ['a'], next)).resolves.toBe(2)
    expect(next).toHaveBeenCalledTimes(1)
  })

  it('a read after an invalidation never joins the request started before it', async () => {
    const { cache } = setup()
    const d = deferred<number>()
    await cache.get('getExecution', ['a'], async () => 0)
    cache.invalidate(queryKey('getExecution', ['a']))
    const before = cache.get('getExecution', ['a'], d.fetcher)
    cache.invalidate(queryKey('getExecution', ['a']))
    const after = cache.get('getExecution', ['a'], d.fetcher)
    expect(d.fetcher).toHaveBeenCalledTimes(2)
    d.calls[1]!.resolve(2)
    d.calls[0]!.resolve(1) // the older generation lands last
    await expect(after).resolves.toBe(2)
    await before
    expect(cache.peek('getExecution', ['a'])).toBe(2)
  })

  it('an abandoned load that resolves anyway publishes nothing', async () => {
    const { cache } = setup()
    const d = deferred<number>()
    const a = new AbortController()
    const p = cache.get('getSession', ['s'], d.fetcher, { signal: a.signal }).catch(() => {})
    a.abort()
    await p
    d.calls[0]!.resolve(9) // a fetcher that ignored its signal
    await flush()
    expect(cache.peek('getSession', ['s'])).toBeUndefined()
  })

  it('a read after clear() never joins, and is never overwritten by, a load from before it', async () => {
    const { cache } = setup()
    const d = deferred<number>()
    const p = cache.get('getSession', ['s'], d.fetcher)
    cache.clear()
    const after = cache.get('getSession', ['s'], d.fetcher)
    expect(d.fetcher).toHaveBeenCalledTimes(2)
    d.calls[1]!.resolve(2)
    d.calls[0]!.resolve(1)
    await expect(after).resolves.toBe(2)
    await p
    expect(cache.peek('getSession', ['s'])).toBe(2)
  })

  it('a failed refresh after an invalidation rejects the read, offers the old value, and keeps it cached', async () => {
    const { cache } = setup()
    await cache.get('getExecution', ['a'], async () => 1)
    cache.invalidate(queryKey('getExecution', ['a']))
    const read = cache.get('getExecution', ['a'], async () => Promise.reject(new Error('404')))
    expect(cache.settled(read)).toEqual({ value: 1, invalidated: true })
    await expect(read).rejects.toThrow('404')
    expect(cache.peek('getExecution', ['a'])).toBe(1)
  })

  it('a failed background refresh of time-stale data keeps serving the old value', async () => {
    const { cache, advance } = setup()
    await cache.get('getExecution', ['a'], async () => 1)
    advance(STALE_AFTER.detail)
    await expect(cache.get('getExecution', ['a'], async () => Promise.reject(new Error('down')))).resolves.toBe(1)
  })

  it('snapshots params and copies data on store', async () => {
    const { cache } = setup()
    const params = ['a']
    const returned = { n: 1 }
    await cache.get('getExecution', params, async () => returned)
    returned.n = 2
    expect(cache.peek('getExecution', ['a'])).toEqual({ n: 1 })
    params[0] = 'b'
    expect(cache.invalidate((e) => e.params[0] === 'a')).toBe(1)
  })

  it('fixtures mode never goes stale by time but still de-dupes and honours invalidation', async () => {
    const { cache, advance } = setup(true)
    const fetcher = vi.fn(async () => 1)
    await Promise.all([cache.get('listWorkflows', [{}], fetcher), cache.get('listWorkflows', [{}], fetcher)])
    advance(STALE_AFTER.detail * 100)
    await cache.get('listWorkflows', [{}], fetcher)
    expect(fetcher).toHaveBeenCalledTimes(1)
    cache.invalidate(() => true)
    await cache.get('listWorkflows', [{}], fetcher)
    expect(fetcher).toHaveBeenCalledTimes(2)
  })

  it('settled exposes a cache hit synchronously, never a load', async () => {
    const { cache } = setup()
    const miss = cache.get('getWorkflow', ['w'], async () => ({ n: 1 }))
    expect(cache.settled(miss)).toBeUndefined()
    await miss
    const hit = cache.get('getWorkflow', ['w'], async () => ({ n: 2 }))
    expect(cache.settled(hit)).toEqual({ value: { n: 1 }, invalidated: false })
    expect(cache.settled(hit.then((v) => v))).toBeUndefined()
  })

  it('hands every caller its own copy', async () => {
    const { cache } = setup()
    const first = await cache.get('getWorkflow', ['w'], async () => ({ name: 'a' }))
    first.name = 'changed'
    expect((await cache.get('getWorkflow', ['w'], async () => ({ name: 'b' }))).name).toBe('a')
  })

  it('track reports the keys a fetcher read synchronously, nested included', () => {
    const { cache } = setup()
    const f = async () => 0
    const { keys } = cache.track(() => {
      void cache.get('getExecution', ['a'], f)
      cache.track(() => void cache.get('getSession', ['s'], f))
    })
    expect(keys).toEqual([queryKey('getExecution', ['a']), queryKey('getSession', ['s'])])
  })

  it('clear forgets entries and evicts unwatched entries past the cap', async () => {
    const cache = new QueryCache({ maxEntries: 2, fixtures: () => true })
    const f = async () => 0
    await cache.get('a', [], f)
    cache.subscribe([queryKey('a', [])], () => {})
    await cache.get('b', [], f)
    await cache.get('c', [], f)
    expect(cache.size).toBe(2)
    expect(cache.peek('a', [])).toBe(0)
    expect(cache.peek('b', [])).toBeUndefined()
    cache.clear()
    expect(cache.size).toBe(0)
  })
})

describe('QueryCache over the real transport', () => {
  it('a read after an invalidation sends its own HTTP request, not the pre-invalidation one', async () => {
    const { configureClient } = await import('./config')
    const { request } = await import('./http')
    const pending: Array<(r: Response) => void> = []
    const fetch = vi.fn(() => new Promise<Response>((resolve) => pending.push(resolve)))
    configureClient({ fixtures: false, baseUrl: '/api/v1', fetch })
    try {
      const cache = new QueryCache({ fixtures: () => false })
      const read = (s: AbortSignal) => request<{ v: number }>('/executions/a', { signal: s })
      const before = cache.get('getExecution', ['a'], read)
      cache.invalidate(queryKey('getExecution', ['a']))
      const after = cache.get('getExecution', ['a'], read)
      expect(fetch).toHaveBeenCalledTimes(2)
      pending[0]!(new Response(JSON.stringify({ v: 0 })))
      pending[1]!(new Response(JSON.stringify({ v: 1 })))
      await expect(after).resolves.toEqual({ v: 1 })
      await before
      expect(cache.peek('getExecution', ['a'])).toEqual({ v: 1 })
    } finally {
      configureClient({ fetch: (...a) => globalThis.fetch(...a) })
    }
  })

  it('two keys reading one URL share one HTTP request within an epoch, and two across an invalidation', async () => {
    const { configureClient } = await import('./config')
    const { request } = await import('./http')
    const pending: Array<(r: Response) => void> = []
    const fetch = vi.fn(() => new Promise<Response>((resolve) => pending.push(resolve)))
    configureClient({ fixtures: false, baseUrl: '/api/v1', fetch })
    try {
      const cache = new QueryCache({ fixtures: () => false })
      const read = (s: AbortSignal) => request<{ v: number }>('/executions', { query: { page_size: 1 }, signal: s })
      const list = cache.get('listExecutions', [{ page_size: 1 }], read)
      const budget = cache.get('getExecutionBudget', [], read)
      expect(fetch).toHaveBeenCalledTimes(1)
      pending[0]!(new Response(JSON.stringify({ v: 0 })))
      await expect(list).resolves.toEqual({ v: 0 })
      await expect(budget).resolves.toEqual({ v: 0 })

      // In flight for one key, then an invalidation of the other: the other must not join it.
      cache.invalidate(queryKey('listExecutions', [{ page_size: 1 }]))
      const refreshed = cache.get('listExecutions', [{ page_size: 1 }], read)
      expect(fetch).toHaveBeenCalledTimes(2)
      cache.invalidate(queryKey('getExecutionBudget', []))
      const budgetAfter = cache.get('getExecutionBudget', [], read)
      expect(fetch).toHaveBeenCalledTimes(3)
      pending[1]!(new Response(JSON.stringify({ v: 1 })))
      pending[2]!(new Response(JSON.stringify({ v: 2 })))
      await expect(refreshed).resolves.toEqual({ v: 1 })
      await expect(budgetAfter).resolves.toEqual({ v: 2 })
    } finally {
      configureClient({ fetch: (...a) => globalThis.fetch(...a) })
    }
  })
})
