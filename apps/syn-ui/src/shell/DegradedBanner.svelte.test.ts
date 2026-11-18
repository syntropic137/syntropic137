// @vitest-environment jsdom
// The degraded-mode banner (#693), mounted inside the real AppShell so the
// test sees what a page sees: GET /health served through the client, read by
// the shell, rendered once above every route.
import { createRawSnippet, flushSync, mount, unmount } from 'svelte'
import { afterEach, describe, expect, it } from 'vitest'
import { configureClient, queryCache } from '@syn137/syn-ui-data'
import { HEALTH_DEGRADED, HEALTH_FULL } from '@syn137/syn-ui-data/fixtures'
import AppShell from './AppShell.svelte'

const settle = async () => {
  for (let i = 0; i < 10; i++) {
    await new Promise((r) => setTimeout(r, 10))
    flushSync()
  }
}

/** Serve /health with `answer`; every other read 404s (the banner must not depend on them). */
function serveHealth(answer: () => Response): void {
  configureClient({
    fixtures: false,
    fetch: async (input) => (new URL(String(input), 'http://x').pathname === '/api/v1/health' ? answer() : new Response('{}', { status: 404 })),
  })
}
const json = (body: unknown, status = 200) => () => new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json' } })

let app: ReturnType<typeof mount> | undefined
async function render(): Promise<HTMLElement> {
  const target = document.createElement('div')
  document.body.append(target)
  const children = createRawSnippet(() => ({ render: () => '<p>page</p>' }))
  app = mount(AppShell, { target, props: { active: 'none', crumbs: [], live: 'live', onsearch: () => {}, children } })
  await settle()
  return target
}

afterEach(() => {
  if (app) unmount(app)
  app = undefined
  document.body.innerHTML = ''
  queryCache.clear()
  configureClient({ fetch: (...args) => globalThis.fetch(...args) })
})

const banners = (el: HTMLElement) => el.querySelectorAll('[data-testid="degraded-banner"]')
const reasons = (el: HTMLElement) => [...el.querySelectorAll('[data-testid="degraded-reason"]')].map((li) => li.textContent)

describe('degraded-mode banner', () => {
  it('shows nothing while the instance is fully serving', async () => {
    serveHealth(json(HEALTH_FULL))
    const el = await render()
    expect(el.textContent).toContain('page')
    expect(banners(el)).toHaveLength(0)
  })

  it('shows nothing when the health read fails', async () => {
    serveHealth(json({ detail: 'boom' }, 500))
    const el = await render()
    expect(banners(el)).toHaveLength(0)
  })

  it('lists every reason the API gives, once, as the API names it', async () => {
    serveHealth(json({ ...HEALTH_DEGRADED, degraded_reasons: ['event_poller', 'disk_space', 'projection_stalled'] }))
    const el = await render()
    expect(banners(el)).toHaveLength(1)
    expect(reasons(el)).toEqual(['event_poller', 'disk_space', 'projection_stalled'])
  })

  it('still shows when degraded comes with no reasons (startup gate), naming the status', async () => {
    serveHealth(json({ status: 'starting', mode: 'degraded', build: HEALTH_FULL.build }))
    const el = await render()
    expect(banners(el)).toHaveLength(1)
    expect(reasons(el)).toEqual([])
    expect(banners(el)[0]!.textContent).toContain('starting')
  })
})
