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
    expect(queryKey('a', [undefined])).toBe('a:[null]')
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
    // stale: old value served, refresh lands, listener hears it
    await expect(cache.get('getExecution', ['a'], fetcher)).resolves.toBe(1)
    await flush()
    expect(heardA).toHaveBeenCalledTimes(2)
    expect(cache.peek('getExecution', ['a'])).toBe(3)
    offB()
    expect(cache.invalidate((e) => e.name === 'getExecution')).toBe(2)
    expect(heardB).not.toHaveBeenCalled()
  })

  it('keeps a load that started before an invalidation stale', async () => {
    const { cache } = setup()
    const d = deferred<number>()
    const p = cache.get('getExecution', ['a'], d.fetcher)
    cache.invalidate(queryKey('getExecution', ['a']))
    d.calls[0]!.resolve(1)
    await p
    const next = vi.fn(async () => 2)
    await expect(cache.get('getExecution', ['a'], next)).resolves.toBe(1)
    expect(next).toHaveBeenCalledTimes(1)
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
    expect(cache.settled(hit)).toEqual({ value: { n: 1 } })
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
