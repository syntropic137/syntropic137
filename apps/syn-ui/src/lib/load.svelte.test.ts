// @vitest-environment jsdom
import { describe, expect, it, vi } from 'vitest'
import { flushSync } from 'svelte'
import { queryCache, queryKey } from '@syn137/syn-ui-data'
import type { StreamSubscriber } from '@syn137/syn-ui-data/live'
import { type Resource, resource } from './load.svelte'

// The activity stream, driven by hand: what a page sees when SSE drops and comes back.
const subscribers = new Set<StreamSubscriber>()
vi.mock('@syn137/syn-ui-data/live', () => ({
  subscribeActivity: (spec: StreamSubscriber) => {
    subscribers.add(spec)
    return () => subscribers.delete(spec)
  },
}))
const reconnect = () => subscribers.forEach((s) => s.onReconnect?.())

const settle = async () => {
  for (let i = 0; i < 5; i++) {
    await new Promise((r) => setTimeout(r, 0))
    flushSync()
  }
}

describe('resource() over the query cache', () => {
  it('a refresh that fails after an invalidation surfaces as error and keeps the last data', async () => {
    queryCache.clear()
    let fail = false
    const fetcher = (s: AbortSignal) =>
      queryCache.get('getExecution', ['load-test'], async () => (fail ? Promise.reject(new Error('404')) : { v: 1 }), { signal: s })
    let r: Resource<{ v: number }> | undefined
    const stop = $effect.root(() => {
      r = resource(fetcher)
    })
    try {
      await settle()
      expect(r!.data).toEqual({ v: 1 })
      expect(r!.error).toBeUndefined()
      fail = true
      queryCache.invalidate(queryKey('getExecution', ['load-test']))
      await settle()
      expect(r!.error).toBeInstanceOf(Error)
      expect(r!.data).toEqual({ v: 1 })
      expect(r!.loading).toBe(false)
    } finally {
      stop()
    }
  })
})

describe('resource() live catch-up (#1924)', () => {
  const mountLive = () => {
    let calls = 0
    const fetcher = async () => ++calls
    const stop = $effect.root(() => {
      resource(fetcher, { live: () => true, liveIntervalMs: 0 })
    })
    return { calls: () => calls, stop }
  }

  // The hub decides what counts as a reconnect (the first open does not, live.test.ts).
  it('refetches when the stream reconnects', async () => {
    const r = mountLive()
    try {
      await settle()
      const loaded = r.calls()
      reconnect()
      await settle()
      expect(r.calls()).toBe(loaded + 1)
    } finally {
      r.stop()
    }
  })

  it('refetches when the tab becomes visible again', async () => {
    const r = mountLive()
    try {
      await settle()
      const loaded = r.calls()
      document.dispatchEvent(new Event('visibilitychange'))
      await settle()
      expect(r.calls()).toBe(loaded + 1)
    } finally {
      r.stop()
    }
  })
})
