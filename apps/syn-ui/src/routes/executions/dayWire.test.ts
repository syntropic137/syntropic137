// ?day= on the wire: the bounds the page computes are the bounds the API receives.
// The page test above the client sees them before the data package rewrites
// anything; this one reads them off the outgoing request (#1940).
import { afterEach, describe, expect, it } from 'vitest'
import { dayBounds } from '@syn137/skyline-core/screens/executions'
import { configureClient, listExecutions, queryCache } from '@syn137/syn-ui-data'

/** An ISO 8601 UTC instant as integer microseconds, the precision the API compares at. */
const micros = (iso: string): bigint => {
  const m = /^(.*T\d{2}:\d{2}:\d{2})(?:\.(\d{1,6}))?Z$/.exec(iso)
  if (!m) throw new Error(`not a UTC instant: ${iso}`)
  return BigInt(Date.parse(`${m[1]}Z`)) * 1000n + BigInt((m[2] ?? '').padEnd(6, '0'))
}

/** What the server admits: both bounds inclusive. */
const admitted = (at: string, after: string, before: string) => micros(after) <= micros(at) && micros(at) <= micros(before)

async function sentBounds(day: string): Promise<{ after: string; before: string }> {
  let url: URL | undefined
  configureClient({
    fixtures: false,
    baseUrl: '/api/v1',
    fetch: async (input) => {
      url = new URL(String(input), 'http://test.invalid')
      return new Response(JSON.stringify({ executions: [], total: 0, page: 1, page_size: 10 }), { status: 200, headers: { 'Content-Type': 'application/json' } })
    },
  })
  await listExecutions({ page: 1, page_size: 10, ...dayBounds(day)! })
  const after = url?.searchParams.get('started_after')
  const before = url?.searchParams.get('started_before')
  if (!after || !before) throw new Error(`no day bounds on the request: ${url}`)
  return { after, before }
}

afterEach(() => {
  queryCache.clear()
  configureClient({ fixtures: true })
})

describe('?day= bounds reach the API unrounded', () => {
  // An ordinary day, a leap day, and a year rollover.
  it.each([
    ['2026-10-13', '2026-10-14'],
    ['2028-02-29', '2028-03-01'],
    ['2026-12-31', '2027-01-01'],
  ])('%s admits its own last microsecond and nothing from %s', async (day, next) => {
    const { after, before } = await sentBounds(day)
    expect(admitted(`${day}T00:00:00Z`, after, before)).toBe(true)
    expect(admitted(`${day}T23:59:59.999999Z`, after, before)).toBe(true)
    expect(admitted(`${next}T00:00:00Z`, after, before)).toBe(false)
    expect(admitted(`${next}T00:00:00.000001Z`, after, before)).toBe(false)
  })
})
