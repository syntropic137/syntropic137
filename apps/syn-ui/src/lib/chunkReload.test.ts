// The branches of the stale-chunk reload that App.svelte.test.ts cannot reach (#2188).
import { describe, expect, it } from 'vitest'
import { ChunkReload, type ReloadHost } from './chunkReload'

function host(storage: ReloadHost['storage']): ReloadHost & { reloads: number } {
  const h = { storage, reloads: 0, isOnline: () => true, reload: () => void (h.reloads += 1) }
  return h
}

const memory = (): ReloadHost['storage'] => {
  const m = new Map<string, string>()
  return { getItem: (k) => m.get(k) ?? null, setItem: (k, v) => void m.set(k, v), removeItem: (k) => void m.delete(k) }
}

describe('ChunkReload', () => {
  it('a second failure while the reload is under way waits for it, without reloading again', () => {
    const h = host(memory())
    const recovery = new ChunkReload(h)
    expect(recovery.recover()).toBe(true)
    expect(recovery.recover()).toBe(true)
    expect(h.reloads).toBe(1)
  })

  it('without sessionStorage nothing could stop a reload loop, so it shows the error', () => {
    const blocked: ReloadHost['storage'] = {
      getItem: () => {
        throw new DOMException('storage disabled', 'SecurityError')
      },
      setItem: () => {
        throw new DOMException('storage disabled', 'SecurityError')
      },
      removeItem: () => {
        throw new DOMException('storage disabled', 'SecurityError')
      },
    }
    const h = host(blocked)
    const recovery = new ChunkReload(h)
    expect(recovery.recover()).toBe(false)
    expect(h.reloads).toBe(0)
    expect(() => recovery.loaded()).not.toThrow()
  })
})
