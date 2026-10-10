// @vitest-environment jsdom
import { describe, expect, it } from 'vitest'
import { flushSync } from 'svelte'
import { queryCache, queryKey } from '@syn137/syn-ui-data'
import { type Resource, resource } from './load.svelte'

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
