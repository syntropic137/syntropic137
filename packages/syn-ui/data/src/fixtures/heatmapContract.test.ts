// Contract: the heatmap fixture speaks the API's field names (codex review of #1856,
// failed-day contract). The generated types are the API's OpenAPI spec, which FastAPI
// builds from HeatmapDayBucketResponse in apps/syn-api/src/syn_api/types.py, so a
// fixture field the model does not declare is a field the live API never sends.
import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { configureClient } from '../client'
import { getContributionHeatmap } from '../index'
import apiTypes from '../generated/api-types.ts?raw'

/** Property names of one schema in the generated types (top level of the object only). */
function schemaProps(source: string, schema: string): string[] {
  const start = source.indexOf(`        ${schema}: {`)
  if (start < 0) throw new Error(`schema ${schema} not in the generated types`)
  const end = source.indexOf('\n        };', start)
  const body = source.slice(start, end)
  return [...body.matchAll(/^ {12}([a-z_]+)\??:/gm)].map((m) => m[1]!)
}

beforeEach(() => configureClient({ fixtures: true, fixtureLatencyMs: 0 }))
afterEach(() => configureClient({ fixtures: false }))

describe('contribution heatmap fixture contract', () => {
  it('reads the bucket fields from the generated API model', () => {
    expect(schemaProps(apiTypes, 'HeatmapDayBucketResponse').sort()).toEqual(['breakdown', 'count', 'date', 'failed'])
  })

  it('sends only fields HeatmapDayBucketResponse declares, failed among them', async () => {
    const allowed = new Set(schemaProps(apiTypes, 'HeatmapDayBucketResponse'))
    const heat = await getContributionHeatmap({ start_date: '2025-10-01', end_date: '2026-12-31' })
    const days = heat.days ?? []
    expect(days.length).toBeGreaterThan(20)
    for (const d of days) {
      for (const key of Object.keys(d)) expect(allowed, `${d.date}.${key}`).toContain(key)
      expect(typeof d.failed).toBe('number')
      // The API mirrors the count into breakdown["failed"] so metric=failed colours by it.
      expect(d.breakdown?.failed).toBe(d.failed)
    }
    expect(days.some((d) => (d.failed ?? 0) > 0)).toBe(true)
  })

  it('never sends the invented failed_executions or failed_count names', async () => {
    const heat = await getContributionHeatmap({ start_date: '2025-10-01', end_date: '2026-12-31' })
    for (const d of heat.days ?? []) {
      expect(d).not.toHaveProperty('failed_executions')
      expect(d).not.toHaveProperty('failed_count')
      expect(d.breakdown ?? {}).not.toHaveProperty('failed_executions')
      expect(d.breakdown ?? {}).not.toHaveProperty('failed_count')
    }
  })
})
