// @vitest-environment jsdom
// Executions list: what the page asks the API for, and what its rows say.
import { flushSync, mount, unmount } from 'svelte'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { ExecutionListResponse } from '@syn137/syn-ui-data/types'
import { startClient } from '../../lib/client'
import { router } from '../../lib/router'

type ListQuery = { started_after?: string; started_before?: string }
const queries: ListQuery[] = []
let decorate: (r: ExecutionListResponse) => ExecutionListResponse = (r) => r
vi.mock('@syn137/syn-ui-data', async (importOriginal) => {
  const real = await importOriginal<typeof import('@syn137/syn-ui-data')>()
  return {
    ...real,
    listExecutions: async (query: Parameters<typeof real.listExecutions>[0], signal?: AbortSignal) => {
      queries.push(query as ListQuery)
      return decorate(await real.listExecutions(query, signal))
    },
  }
})

const settle = async () => {
  for (let i = 0; i < 20; i++) {
    await new Promise((r) => setTimeout(r, 25))
    flushSync()
  }
}

async function mountList(search: string) {
  router.search = search
  const { default: List } = await import('./List.svelte')
  const target = document.createElement('div')
  document.body.append(target)
  const app = mount(List, { target, props: { params: {} } })
  await settle()
  return { target, stop: () => (unmount(app), target.remove()) }
}

beforeEach(() => {
  startClient(true)
  queries.length = 0
  decorate = (r) => r
})
afterEach(() => {
  startClient(false)
  router.search = ''
})

describe('Executions list ?day= (#1938)', () => {
  it('asks for exactly that UTC day and shows it as a removable chip', async () => {
    const { target, stop } = await mountList('?day=2026-10-13')
    try {
      expect(queries.at(-1)).toMatchObject({ started_after: '2026-10-13T00:00:00.000Z', started_before: '2026-10-13T23:59:59.999Z' })
      const chip = [...target.querySelectorAll('button')].find((b) => b.textContent?.includes('Started 2026-10-13 UTC'))
      expect(chip).toBeDefined()
      chip!.click()
      await settle()
      expect(router.query.get('day')).toBeNull()
      expect(queries.at(-1)?.started_before).toBeUndefined()
    } finally {
      stop()
    }
  }, 30_000)

  it('ignores a ?day= that is not a date and keeps the time window', async () => {
    const { stop } = await mountList('?day=bogus')
    try {
      expect(queries.at(-1)?.started_before).toBeUndefined()
      expect(queries.at(-1)?.started_after).toBeDefined()
    } finally {
      stop()
    }
  }, 30_000)
})

describe('Executions list resume badge (#1926)', () => {
  it('badges a resumed run with the run it resumed from, and only that run', async () => {
    decorate = (r) => ({
      ...r,
      executions: r.executions.map((e, i) => (i === 0 ? { ...e, resumed_from: { parent_execution_id: 'exec-parent-1', resume_phase_id: 'p2' } } : e)),
    })
    const { target, stop } = await mountList('?window=all')
    try {
      const badges = [...target.querySelectorAll('.sky-run-row__tag')].filter((t) => t.textContent === 'Resumed')
      expect(badges).toHaveLength(1)
      expect(badges[0]!.getAttribute('title')).toBe('Resumed from exec-parent-1')
    } finally {
      stop()
    }
  }, 30_000)
})
