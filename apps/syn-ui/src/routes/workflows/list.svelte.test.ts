// @vitest-environment jsdom
// Workflows: the page's request count does not grow with the catalogue (#1872).
// It used to fetch every workflow's detail for its skills and every card's
// trend on its own, so 51 workflows cost ~64 requests and the gateway
// answered 429. Counted at fetch, so a request added in any layer shows.
import { flushSync, mount, unmount } from 'svelte'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { configureClient, queryCache } from '@syn137/syn-ui-data'

const settle = async () => {
  for (let i = 0; i < 20; i++) {
    await new Promise((r) => setTimeout(r, 10))
    flushSync()
  }
}

const summary = (i: number) => ({
  id: `wf-${i}`,
  name: `Workflow ${i}`,
  workflow_type: 'research',
  classification: 'simple',
  phase_count: 2,
  runs_count: 3,
  is_archived: false,
  requires_repos: false,
  tags: [],
  // Only the list carries skills now: a chip that renders proves it is read from here.
  skills: i === 0 ? [{ name: 'list-only-skill', source_url: null, version: null, name_overridden: false }] : [],
})

const point = (day: number, seconds: number) => ({
  execution_id: `x-${day}`,
  date: new Date(Date.UTC(2026, 9, day)).toISOString(),
  status: 'completed',
  workflow_version: null,
  cost_usd: null,
  cost_is_lower_bound: false,
  cost_display: '$0.00',
  duration_seconds: seconds,
  duration_is_lower_bound: false,
  duration_display: `${seconds}s`,
  tokens: 0,
  phase_durations: [],
})

let paths: string[] = []

function serve(count: number): typeof fetch {
  const workflows = Array.from({ length: count }, (_, i) => summary(i))
  return async (input) => {
    const url = new URL(String(input), 'http://ui.test')
    const path = url.pathname.replace(/^\/api\/v1/, '')
    paths.push(path)
    const json = (body: unknown) => new Response(JSON.stringify(body), { status: 200, headers: { 'content-type': 'application/json' } })
    if (path === '/workflows') return json({ workflows, total: count, page: 1, page_size: count })
    if (path === '/workflows/trends') {
      const ids = (url.searchParams.get('ids') ?? '').split(',')
      // Every run 20% slower than the one before: each card should read Slower.
      const items = [point(5, 144), point(4, 120), point(3, 100)]
      return json({ trends: ids.map((workflow_id) => ({ workflow_id, items, total: 3, page: 1, page_size: 12, definition_version: null, definition_changed_at: null, definition_changes: [] })) })
    }
    return new Response(JSON.stringify({ detail: 'not served' }), { status: 404 })
  }
}

beforeEach(() => {
  vi.stubGlobal(
    'ResizeObserver',
    class {
      observe() {}
      unobserve() {}
      disconnect() {}
    },
  )
  queryCache.clear()
  paths = []
})
afterEach(() => {
  configureClient({ fixtures: false, fetch: (...args) => globalThis.fetch(...args) })
  vi.unstubAllGlobals()
})

async function load(count: number): Promise<{ paths: string[]; target: HTMLElement }> {
  configureClient({ fixtures: false, fixtureLatencyMs: 0, fetch: serve(count) })
  const { default: List } = await import('./List.svelte')
  const target = document.createElement('div')
  document.body.append(target)
  const app = mount(List, { target, props: { params: {} } })
  await settle()
  const snapshot = { paths: [...paths], target: target.cloneNode(true) as HTMLElement }
  unmount(app)
  target.remove()
  return snapshot
}

describe('Workflows page requests (#1872)', () => {
  it.each([5, 50])('makes two requests for %i workflows: the list and one trend batch', async (count) => {
    const { paths, target } = await load(count)

    expect(paths.sort()).toEqual(['/workflows', '/workflows/trends'])
    // The cards rendered from those two answers: skills from the list, trends from the batch.
    expect(target.querySelectorAll('[data-sky-row]').length).toBe(Math.min(count, 12))
    expect(target.textContent).toContain('list-only-skill')
    expect(target.textContent).toContain('Slower')
    expect(target.textContent).not.toContain('Loading the duration trend')
  }, 30_000)

  it('makes the same number of requests for 5 and for 50 workflows', async () => {
    const few = (await load(5)).paths.length
    queryCache.clear()
    paths = []
    const many = (await load(50)).paths.length
    expect(many).toBe(few)
  }, 30_000)
})
