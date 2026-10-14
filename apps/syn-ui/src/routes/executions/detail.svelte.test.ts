// @vitest-environment jsdom
// Execution page: the phase running now stands out from the rest (#1925).
import { flushSync, mount, unmount } from 'svelte'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { listExecutions } from '@syn137/syn-ui-data'
import { startClient } from '../../lib/client'

const settle = async () => {
  for (let i = 0; i < 20; i++) {
    await new Promise((r) => setTimeout(r, 25))
    flushSync()
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
  startClient(true)
})
afterEach(() => {
  startClient(false)
  vi.unstubAllGlobals()
})

describe('Execution detail phases', () => {
  it('marks the running phase row, and only that row', async () => {
    const running = (await listExecutions({ statuses: ['running'] })).executions[0]!
    const { default: Detail } = await import('./Detail.svelte')
    const target = document.createElement('div')
    document.body.append(target)
    const app = mount(Detail, { target, props: { params: { executionId: running.workflow_execution_id } } })
    try {
      await settle()
      const rows = [...target.querySelectorAll('.sky-exec__phase')]
      expect(rows.length).toBeGreaterThan(1)
      const lit = rows.filter((r) => r.hasAttribute('data-running'))
      expect(lit).toHaveLength(1)
      expect(lit[0]!.textContent).toContain('Running')
    } finally {
      unmount(app)
      target.remove()
    }
  }, 30_000)
})
