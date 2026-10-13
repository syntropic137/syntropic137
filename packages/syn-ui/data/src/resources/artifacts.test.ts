import { afterEach, describe, expect, it } from 'vitest'
import { configureClient } from '../client'
import { countArtifactsByExecution, listArtifacts } from './artifacts'

afterEach(() => {
  configureClient({ fixtures: false, fixtureLatencyMs: 120 })
})

describe('countArtifactsByExecution (parity-2 #4: a run group counted only the loaded page)', () => {
  it("returns each run's API total, not its share of a page", async () => {
    configureClient({ fixtures: true, fixtureLatencyMs: 0 })
    const page = await listArtifacts({ page: 1, page_size: 2 })
    const execs = [...new Set(page.artifacts.map((a) => ('execution_id' in a ? String(a.execution_id) : '')).filter(Boolean))]
    expect(execs.length).toBeGreaterThan(0)
    const totals = await countArtifactsByExecution([...execs, ...execs])
    expect(Object.keys(totals)).toEqual(execs)
    for (const id of execs) {
      const all = await listArtifacts({ page: 1, page_size: 100 }, { execution_id: id })
      expect(totals[id]).toBe(all.total)
    }
    // At least one run has more files than the two-row page shows of it.
    expect(execs.some((id) => totals[id]! > page.artifacts.filter((a) => 'execution_id' in a && a.execution_id === id).length)).toBe(true)
  })
})
