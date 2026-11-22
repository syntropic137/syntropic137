// @vitest-environment jsdom
// A tab left open across a deploy asks for a route chunk the new build removed (#2188).
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { flushSync, mount, unmount } from 'svelte'
import { ChunkReload, type ReloadHost } from './lib/chunkReload'
import { startClient } from './lib/client'

const nav = vi.hoisted(() => ({
  /** What the next route load does: a chunk that is gone, or one that loads. */
  chunk: 'gone' as 'gone' | 'ok',
  reload: (() => {}) as () => void,
  /** The recovery of the page open now; a reload starts a new one. */
  page: null as null | Pick<ChunkReload, 'recover' | 'loaded'>,
}))

vi.mock('./lib/router', async (importOriginal) => {
  const actual = await importOriginal<typeof import('./lib/router')>()
  const route = {
    path: '/executions/:executionId',
    area: 'executions',
    title: () => 'Execution',
    crumbs: () => [],
    load: () =>
      nav.chunk === 'gone'
        ? Promise.reject(new TypeError('Failed to fetch dynamically imported module: /assets/Detail-OLDHASH.js'))
        : import('./routes/NotFound.svelte'),
  }
  return {
    ...actual,
    router: { path: '/executions/e1', match: { route, params: { executionId: 'e1' }, key: 'k' }, navigate: () => {}, start: () => () => {} },
  }
})

// The real recovery, one per page load, over jsdom's sessionStorage (which
// outlives the "reload"), with only location.reload replaced: jsdom cannot navigate.
vi.mock('./lib/chunkReload', async (importOriginal) => {
  const actual = await importOriginal<typeof import('./lib/chunkReload')>()
  return { ...actual, chunkReload: { recover: () => nav.page!.recover(), loaded: () => nav.page!.loaded() } }
})
const host: ReloadHost = { storage: sessionStorage, isOnline: () => navigator.onLine, reload: () => nav.reload() }

let reloads = 0

/** Open the app as the browser does after a reload: a fresh page, the same sessionStorage. */
async function openPage(): Promise<{ target: HTMLElement; close: () => void }> {
  nav.page = new ChunkReload(host)
  const { default: App } = await import('./App.svelte')
  const target = document.createElement('div')
  document.body.append(target)
  const app = mount(App, { target })
  // Until the route load has played out: a reload, the error page, or the page itself.
  const before = reloads
  for (let i = 0; i < 500 && reloads === before && !target.querySelector('.sky-route-error, .sky-notfound'); i++) {
    await new Promise((r) => setTimeout(r, 10))
    flushSync()
  }
  return {
    target,
    close: () => {
      unmount(app)
      target.remove()
    },
  }
}

const errorShown = (target: HTMLElement) => target.querySelector('.sky-route-error') !== null

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
  sessionStorage.clear()
  reloads = 0
  nav.reload = () => (reloads += 1)
})
afterEach(() => {
  startClient(false)
  vi.unstubAllGlobals()
})

describe('a route chunk that is gone after a deploy', () => {
  it('reloads once instead of showing the error, then shows it if the reloaded page fails too', async () => {
    nav.chunk = 'gone'
    const stale = await openPage()
    try {
      expect(reloads).toBe(1)
      expect(errorShown(stale.target)).toBe(false)
    } finally {
      stale.close()
    }

    const reloaded = await openPage()
    try {
      expect(reloads).toBe(1)
      expect(errorShown(reloaded.target)).toBe(true)
      expect(reloaded.target.textContent).toContain('This page did not load')
    } finally {
      reloaded.close()
    }
  }, 30_000)

  it('a page that loads re-arms the reload for the next deploy', async () => {
    nav.chunk = 'gone'
    ;(await openPage()).close()
    expect(reloads).toBe(1)

    nav.chunk = 'ok'
    const fresh = await openPage()
    try {
      expect(errorShown(fresh.target)).toBe(false)
    } finally {
      fresh.close()
    }

    nav.chunk = 'gone'
    const nextDeploy = await openPage()
    try {
      expect(reloads).toBe(2)
      expect(errorShown(nextDeploy.target)).toBe(false)
    } finally {
      nextDeploy.close()
    }
  }, 30_000)

  it('shows the error without reloading while offline', async () => {
    vi.spyOn(navigator, 'onLine', 'get').mockReturnValue(false)
    nav.chunk = 'gone'
    const page = await openPage()
    try {
      expect(reloads).toBe(0)
      expect(errorShown(page.target)).toBe(true)
    } finally {
      page.close()
      vi.restoreAllMocks()
    }
  }, 30_000)
})
