// @vitest-environment jsdom
// Execution page: the phase running now stands out from the rest (#1925),
// and each repository's commit is shown for the run and where a phase differs (#1004).
import { flushSync, mount, unmount } from 'svelte'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { getExecution, listExecutions } from '@syn137/syn-ui-data'
import { RUNS } from '@syn137/syn-ui-data/fixtures'
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
    const running = (await listExecutions({ page: 1, page_size: 10, statuses: ['running'] })).executions[0]!
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

async function render(executionId: string): Promise<{ target: HTMLElement; done: () => void }> {
  const { default: Detail } = await import('./Detail.svelte')
  const target = document.createElement('div')
  document.body.append(target)
  const app = mount(Detail, { target, props: { params: { executionId } } })
  await settle()
  return {
    target,
    done: () => {
      unmount(app)
      target.remove()
    },
  }
}

const runCommits = (target: HTMLElement) => target.querySelector('.sky-page-header .sky-exec__commits')?.textContent?.replace(/\s+/g, ' ').trim()
const phaseCommits = (target: HTMLElement) => [...target.querySelectorAll('.sky-exec__phase')].map((row) => row.querySelector('.sky-exec__commits')?.textContent?.replace(/\s+/g, ' ').trim() ?? null)

describe('Execution detail commits (#1004)', () => {
  // The pr-review run an hour ago: recorded commits, and its last phase was re-checked out at another.
  const recheckout = RUNS[1]!.id
  // The board's canonical run is a day old, from before commits were captured.
  const older = RUNS[2]!.id

  it("shows each repository's short commit for the run, the full SHA only on copy", async () => {
    const d = await getExecution(recheckout)
    const commit = d.source_commits![0]!
    const { target, done } = await render(recheckout)
    try {
      expect(runCommits(target)).toBe(`Commits: ${commit.repository} @ ${commit.sha!.slice(0, 7)}`)
      expect(target.querySelector('.sky-page-header .sky-exec__commits')!.textContent).not.toContain(commit.sha!)
      const copy = target.querySelector<HTMLButtonElement>('.sky-page-header .sky-exec__commits button')
      expect(copy?.getAttribute('aria-label')).toBe(`Copy the full commit for ${commit.repository}`)
    } finally {
      done()
    }
  }, 30_000)

  it('shows a phase checked out at another commit, and no line on phases that match the run', async () => {
    const d = await getExecution(recheckout)
    const differing = d.phases[2]!.checked_out_commits![0]!
    expect(differing.sha).not.toBe(d.source_commits![0]!.sha)
    const { target, done } = await render(recheckout)
    try {
      expect(phaseCommits(target)).toEqual([null, null, `Checked out: ${differing.repository} @ ${differing.sha!.slice(0, 7)}`])
    } finally {
      done()
    }
  }, 30_000)

  it('says the commit was not recorded for a run from before capture, and nothing per phase', async () => {
    const d = await getExecution(older)
    expect(d.source_commits).toBeNull()
    const { target, done } = await render(older)
    try {
      expect(runCommits(target)).toBe('Commits: commit not recorded (older run)')
      expect(phaseCommits(target).every((line) => line === null)).toBe(true)
    } finally {
      done()
    }
  }, 30_000)
})
