import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { configureClient } from '../client'
import { queryCache } from '../client/queryCache'
import { getHealth } from '../resources/observability'

beforeEach(() => {
  queryCache.clear()
})
afterEach(() => {
  configureClient({ fixtures: false, fixtureLatencyMs: 120, fetch: (...args) => globalThis.fetch(...args) })
  queryCache.clear()
})

describe('getHealth', () => {
  it('reads GET /health on the API root, beside /version', async () => {
    const urls: string[] = []
    configureClient({
      fixtures: false,
      fetch: async (input) => {
        urls.push(String(input))
        return new Response(JSON.stringify({ status: 'healthy', mode: 'full', build: {} }), { headers: { 'content-type': 'application/json' } })
      },
    })
    expect((await getHealth()).mode).toBe('full')
    expect(urls).toEqual(['/api/v1/health'])
  })

  it('fixtures answer fully serving, with no reasons', async () => {
    configureClient({ fixtures: true, fixtureLatencyMs: 0 })
    const h = await getHealth()
    expect(h.mode).toBe('full')
    expect(h.degraded_reasons).toBeUndefined()
  })
})
