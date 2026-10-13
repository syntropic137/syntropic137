// Run: node --experimental-strip-types --test bridge/index.test.ts
import assert from 'node:assert/strict'
import { afterEach, describe, it } from 'node:test'

import {
  DEFAULT_DESKTOP_API_BASE_URL,
  EVENTS,
  effectiveApiBaseUrl,
  getSettings,
  isDesktop,
  onCommandPalette,
  onNavigate,
  setLiveState,
  startDesktop,
} from './index.ts'

type Handler = (e: { payload: unknown }) => void

function fakeTauri(results: Record<string, unknown> = {}) {
  const handlers = new Map<string, Set<Handler>>()
  const calls: Array<[string, unknown]> = []
  const g = globalThis as Record<string, unknown>
  g.__TAURI__ = {
    core: {
      invoke: async (cmd: string, args?: unknown) => {
        calls.push([cmd, args])
        return results[cmd] ?? null
      },
    },
    event: {
      listen: async (name: string, h: Handler) => {
        if (!handlers.has(name)) handlers.set(name, new Set())
        handlers.get(name)!.add(h)
        return () => handlers.get(name)!.delete(h)
      },
    },
  }
  const emit = (name: string, payload: unknown) => handlers.get(name)?.forEach((h) => h({ payload }))
  return { calls, emit, handlers }
}

const tick = () => new Promise((r) => setTimeout(r, 0))

afterEach(() => {
  delete (globalThis as Record<string, unknown>).__TAURI__
})

describe('outside Tauri', () => {
  it('is inert', async () => {
    assert.equal(isDesktop(), false)
    const off = onCommandPalette(() => assert.fail('no events on the web'))
    off()
    assert.equal(await getSettings(), null)
    await setLiveState('live')
    const stop = await startDesktop({ navigate: () => assert.fail(), openCommandPalette: () => assert.fail() })
    stop()
  })
})

describe('inside Tauri', () => {
  it('forwards events and stops after unsubscribe', async () => {
    const t = fakeTauri()
    let n = 0
    const off = onCommandPalette(() => n++)
    await tick()
    t.emit(EVENTS.commandPalette, null)
    assert.equal(n, 1)
    off()
    t.emit(EVENTS.commandPalette, null)
    assert.equal(n, 1)
  })

  it('unsubscribe before listen resolves still unlistens', async () => {
    const t = fakeTauri()
    const off = onCommandPalette(() => assert.fail())
    off()
    await tick()
    assert.equal(t.handlers.get(EVENTS.commandPalette)?.size ?? 0, 0)
  })

  it('only forwards absolute app paths', async () => {
    const t = fakeTauri()
    const seen: string[] = []
    onNavigate((p) => seen.push(p))
    await tick()
    t.emit(EVENTS.navigate, { path: '/executions/abc' })
    t.emit(EVENTS.navigate, { path: 'https://evil.example' })
    t.emit(EVENTS.navigate, null)
    assert.deepEqual(seen, ['/executions/abc'])
  })

  it('sends the live state to the shell', async () => {
    const t = fakeTauri()
    await setLiveState('offline')
    assert.deepEqual(t.calls, [['set_live_state', { state: 'offline' }]])
  })

  it('startDesktop applies settings, then the pending deep link', async () => {
    fakeTauri({
      get_settings: { apiBaseUrl: 'http://syn.local:8137/api/v1', globalShortcut: 'CmdOrCtrl+K' },
      desktop_ready: '/executions/exec_1',
    })
    const order: string[] = []
    await startDesktop({
      navigate: (p) => order.push(`nav ${p}`),
      openCommandPalette: () => {},
      configureApi: (u) => order.push(`api ${u}`),
    })
    assert.deepEqual(order, ['api http://syn.local:8137/api/v1', 'nav /executions/exec_1'])
  })
})

describe('effectiveApiBaseUrl', () => {
  const s = (apiBaseUrl: string | null) => ({ apiBaseUrl, globalShortcut: '' })
  it('prefers the saved URL', () => {
    assert.equal(effectiveApiBaseUrl(s('http://x:1'), { port: '5174' }), 'http://x:1')
  })
  it('keeps the dev proxy under the vite dev server', () => {
    assert.equal(effectiveApiBaseUrl(s(null), { port: '5174' }), null)
  })
  it('falls back to the selfhost gateway in a packaged app', () => {
    assert.equal(effectiveApiBaseUrl(s(null), { port: '' }), DEFAULT_DESKTOP_API_BASE_URL)
  })
  it('does nothing on the web', () => {
    assert.equal(effectiveApiBaseUrl(null, { port: '' }), null)
  })
})
