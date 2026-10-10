// @vitest-environment jsdom
// Overview: the Active days headline's own request can fail (codex review 2 of #1856).
import { flushSync, mount, unmount } from 'svelte'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { startClient } from '../../lib/client'
import { heatmapPeriod } from '@syn137/skyline-core/screens/overview'
import { dayFromMs } from '@syn137/skyline-core/geometry'

// The 52-week headline request fails; the scroller's 13-week pages still answer from fixtures.
const period = heatmapPeriod(dayFromMs(Date.now()), 52)
let failPeriod = true
vi.mock('@syn137/syn-ui-data', async (importOriginal) => {
  const real = await importOriginal<typeof import('@syn137/syn-ui-data')>()
  return {
    ...real,
    getContributionHeatmap: (params: { start_date?: string; end_date?: string } = {}, signal?: AbortSignal) =>
      failPeriod && params.start_date === period.start_date && params.end_date === period.end_date
        ? Promise.reject(new real.ApiError(503, 'heatmap down'))
        : real.getContributionHeatmap(params, signal),
  }
})

const settle = async () => {
  for (let i = 0; i < 40; i++) {
    await new Promise((r) => setTimeout(r, 25))
    flushSync()
  }
}

beforeEach(() => {
  // jsdom has no ResizeObserver; Svelte's bind:clientWidth needs one.
  vi.stubGlobal(
    'ResizeObserver',
    class {
      observe() {}
      unobserve() {}
      disconnect() {}
    },
  )
  startClient(true)
  failPeriod = true
})
afterEach(() => {
  startClient(false)
  vi.unstubAllGlobals()
})

describe('Overview Active days headline', () => {
  it('says Unavailable with a Retry when the period request fails, and recovers on Retry', async () => {
    const { default: Overview } = await import('./Overview.svelte')
    const target = document.createElement('div')
    document.body.append(target)
    const app = mount(Overview, { target, props: { params: {} } })
    try {
      await settle()
      const stat = [...target.querySelectorAll('.sky-ov-stats > div')].find((d) => d.querySelector('dt')?.textContent === 'Active days')!
      expect(stat.querySelector('dd')?.textContent).toContain('Unavailable')
      const retry = stat.querySelector<HTMLButtonElement>('button')!
      expect(retry.getAttribute('aria-label')).toBe('Retry active days')
      failPeriod = false
      retry.click()
      await settle()
      expect(stat.querySelector('dd')?.textContent).toMatch(/^\s*\d+\s*$/)
      expect(stat.querySelector('button')).toBeNull()
    } finally {
      unmount(app)
      target.remove()
    }
  })
})
