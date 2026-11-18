// @vitest-environment jsdom
// The degraded-mode banner (#693), mounted inside the real AppShell so the
// test sees what a page sees: the shell reads getHealth and renders the banner
// once above every route.
import { createRawSnippet, flushSync, mount, unmount } from 'svelte'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { Health } from '@syn137/syn-ui-data'
import { HEALTH_DEGRADED, HEALTH_FULL } from '@syn137/syn-ui-data/fixtures'
import { startClient } from '../lib/client'
import AppShell from './AppShell.svelte'

// null: the real getHealth, answered by the /health fixture. Otherwise what this test serves instead.
let served: (() => Promise<Health>) | null = null
// Modes the real read answered, so a hidden banner is known to have seen an answer.
const fixtureReads: string[] = []
vi.mock('@syn137/syn-ui-data', async (importOriginal) => {
  const real = await importOriginal<typeof import('@syn137/syn-ui-data')>()
  const read = (signal?: AbortSignal) =>
    real.getHealth(signal).then((h) => {
      fixtureReads.push(h.mode)
      return h
    })
  return { ...real, getHealth: (signal?: AbortSignal) => (served ? served() : read(signal)) }
})
const answer = (health: Health) => () => Promise.resolve(health)

const settle = async () => {
  for (let i = 0; i < 40; i++) {
    await new Promise((r) => setTimeout(r, 25))
    flushSync()
  }
}

let app: ReturnType<typeof mount> | undefined
async function render(): Promise<HTMLElement> {
  const target = document.createElement('div')
  document.body.append(target)
  const children = createRawSnippet(() => ({ render: () => '<p>page</p>' }))
  app = mount(AppShell, { target, props: { active: 'none', crumbs: [], live: 'live', onsearch: () => {}, children } })
  await settle()
  return target
}

beforeEach(() => {
  startClient(true)
  served = null
  fixtureReads.length = 0
})
afterEach(() => {
  if (app) unmount(app)
  app = undefined
  document.body.innerHTML = ''
  startClient(false)
})

const banners = (el: HTMLElement) => el.querySelectorAll('[data-testid="degraded-banner"]')
const reasons = (el: HTMLElement) => [...el.querySelectorAll('[data-testid="degraded-reason"]')].map((li) => li.textContent)

describe('degraded-mode banner', () => {
  it('shows nothing while the instance is fully serving (the real read, from the /health fixture)', async () => {
    const el = await render()
    expect(el.textContent).toContain('page')
    expect(fixtureReads).toContain('full')
    expect(banners(el)).toHaveLength(0)
  })

  it('shows nothing when the health read fails', async () => {
    served = async () => {
      throw new Error('health down')
    }
    const el = await render()
    expect(banners(el)).toHaveLength(0)
  })

  it('lists every reason the API gives, once, as the API names it', async () => {
    served = answer({ ...HEALTH_DEGRADED, degraded_reasons: ['event_poller', 'disk_space', 'projection_stalled'] })
    const el = await render()
    expect(banners(el)).toHaveLength(1)
    expect(reasons(el)).toEqual(['event_poller', 'disk_space', 'projection_stalled'])
  })

  it('still shows when degraded comes with no reasons (startup gate), naming the status', async () => {
    served = answer({ status: 'starting', mode: 'degraded', build: HEALTH_FULL.build })
    const el = await render()
    expect(banners(el)).toHaveLength(1)
    expect(reasons(el)).toEqual([])
    expect(banners(el)[0]!.textContent).toContain('starting')
  })
})
