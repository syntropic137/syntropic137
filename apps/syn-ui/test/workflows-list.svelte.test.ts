// @vitest-environment jsdom
// Workflows: the page's request count does not grow with the catalogue (#1872).
// It used to fetch every workflow's detail for its skills and every card's
// trend on its own, so 51 workflows cost ~64 requests and the gateway
// answered 429. Counted at fetch, so a request added in any layer shows.
//
// Outside src/ on purpose: ADR-074 forbids src/ from touching the transport,
// and this test has to replace it to count what the page really sends.
import { flushSync, mount, unmount } from 'svelte'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { configureClient, invalidateTargets, queryCache } from '@syn137/syn-ui-data'

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

// Words the client could never derive from the points: the card must render the API's label.
const label = (id: string, version: number) => ({
  kind: 'slower',
  pct: 44,
  runs: 3,
  word_display: `server-word ${id} v${version}`,
  sub_display: `server-sub ${id}`,
  label_display: `server-label ${id}`,
})

let paths: string[] = []
/** Bumped to model a run finishing: the next trend batch answers with new labels. */
let version = 1
/** While true the trend batch answers 503. */
let failTrends = false

function serve(count: number): typeof fetch {
  const workflows = Array.from({ length: count }, (_, i) => summary(i))
  return async (input) => {
    const url = new URL(String(input), 'http://ui.test')
    const path = url.pathname.replace(/^\/api\/v1/, '')
    paths.push(path)
    const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json' } })
    if (path === '/workflows') return json({ workflows, total: count, page: 1, page_size: count })
    if (path === '/workflows/trends') {
      if (failTrends) return json({ detail: 'trends down' }, 503)
      const ids = (url.searchParams.get('ids') ?? '').split(',')
      const items = [point(5, 144), point(4, 120), point(3, 100)]
      return json({
        trends: ids.map((workflow_id) => ({
          workflow_id,
          items,
          total: 3,
          page: 1,
          page_size: 12,
          definition_version: null,
          definition_changed_at: null,
          definition_changes: [],
          duration_trend: label(workflow_id, version),
        })),
      })
    }
    return json({ detail: 'not served' }, 404)
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
  version = 1
  failTrends = false
})
afterEach(() => {
  configureClient({ fixtures: false, fetch: (...args) => globalThis.fetch(...args) })
  vi.unstubAllGlobals()
})

async function open(count: number) {
  configureClient({ fixtures: false, fixtureLatencyMs: 0, fetch: serve(count) })
  const { default: List } = await import('../src/routes/workflows/List.svelte')
  const target = document.createElement('div')
  document.body.append(target)
  const app = mount(List, { target, props: { params: {} } })
  await settle()
  return {
    target,
    close() {
      unmount(app)
      target.remove()
    },
  }
}

/** Each card's trend text, by workflow id. */
const cardTrends = (target: HTMLElement) =>
  Object.fromEntries([...target.querySelectorAll('[data-sky-row]')].map((card) => [card.querySelector('.sky-wfs__slug')?.textContent, card.querySelector('.sky-wfs__trend')?.textContent ?? '']))

describe('Workflows page requests (#1872)', () => {
  it.each([5, 50])('makes two requests for %i workflows: the list and one trend batch', async (count) => {
    const page = await open(count)
    try {
      expect([...paths].sort()).toEqual(['/workflows', '/workflows/trends'])
      // The cards rendered from those two answers: skills from the list, each card its own server label.
      const shown = Math.min(count, 12)
      expect(page.target.querySelectorAll('[data-sky-row]').length).toBe(shown)
      expect(page.target.textContent).toContain('list-only-skill')
      const trends = Object.entries(cardTrends(page.target))
      expect(trends).toHaveLength(shown)
      for (const [id, text] of trends) {
        expect(text).toContain(`server-word ${id} v1`)
        expect(text).toContain(`server-sub ${id}`)
      }
      expect(page.target.textContent).not.toContain('Loading')
    } finally {
      page.close()
    }
  }, 30_000)

  it('makes the same number of requests for 5 and for 50 workflows', async () => {
    const few = await open(5)
    few.close()
    const fewCount = paths.length
    queryCache.clear()
    paths = []
    const many = await open(50)
    many.close()
    expect(paths.length).toBe(fewCount)
  }, 30_000)

  it('redraws every card from one new batch when a run finishes', async () => {
    const page = await open(50)
    try {
      expect(Object.values(cardTrends(page.target)).every((t) => t.includes(' v1'))).toBe(true)
      paths = []
      version = 2
      // What the live stream does on WorkflowCompleted (live/invalidate.ts).
      invalidateTargets([{ name: 'getWorkflowTrends' }])
      await settle()

      expect(paths).toEqual(['/workflows/trends'])
      const trends = Object.entries(cardTrends(page.target))
      expect(trends).toHaveLength(12)
      for (const [id, text] of trends) expect(text).toContain(`server-word ${id} v2`)
    } finally {
      page.close()
    }
  }, 30_000)

  it('says the trends are unavailable when the batch fails, and recovers on Retry', async () => {
    failTrends = true
    const page = await open(5)
    try {
      expect(page.target.textContent).toContain('Duration trends did not load.')
      expect(cardTrends(page.target)['wf-0']).toContain('Unavailable')
      expect(page.target.textContent).not.toContain('Loading the duration trend')

      failTrends = false
      paths = []
      const retry = [...page.target.querySelectorAll('button')].find((b) => b.textContent?.trim() === 'Retry')!
      retry.click()
      await settle()

      expect(paths).toEqual(['/workflows/trends'])
      expect(page.target.textContent).not.toContain('Duration trends did not load.')
      expect(cardTrends(page.target)['wf-0']).toContain('server-word wf-0 v1')
    } finally {
      page.close()
    }
  }, 30_000)
})
