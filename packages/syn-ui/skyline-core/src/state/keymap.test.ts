import { describe, expect, it } from 'vitest'
import { CHORD_MS, GOTO_KEYS, KEYMAP, KEYMAP_IDLE, keyLabel, keymapGroups, keymapStep, keyToken, sequenceLabel, shortcutFor, type KeyInput, type KeymapState } from './keymap'

const press = (key: string, over: Partial<KeyInput> = {}): KeyInput => ({ key, mod: false, alt: false, typing: false, modal: false, at: 0, ...over })

function feed(keys: (string | KeyInput)[]) {
  let state: KeymapState = KEYMAP_IDLE
  const out = []
  for (const k of keys) {
    const r = keymapStep(state, typeof k === 'string' ? press(k) : k)
    state = r.state
    out.push(r)
  }
  return out
}

describe('keymap', () => {
  it('jumps to every section with g + key', () => {
    for (const [section, key] of Object.entries(GOTO_KEYS)) {
      const [first, second] = feed(['g', key])
      expect(first!.handled).toBe(true)
      expect(first!.action).toBeNull()
      expect(second!.action).toEqual({ type: 'goto', section })
    }
  })

  it('maps the single keys', () => {
    expect(feed(['j'])[0]!.action).toEqual({ type: 'row', move: 'next' })
    expect(feed(['ArrowUp'])[0]!.action).toEqual({ type: 'row', move: 'prev' })
    expect(feed(['Enter'])[0]!.action).toEqual({ type: 'open' })
    expect(feed(['Escape'])[0]!.action).toEqual({ type: 'back' })
    expect(feed(['Backspace'])[0]!.action).toEqual({ type: 'back' })
    expect(feed(['/'])[0]!.action).toEqual({ type: 'search' })
    expect(feed(['?'])[0]!.action).toEqual({ type: 'help' })
    expect(feed([press('k', { mod: true })])[0]!.action).toEqual({ type: 'palette' })
    expect(feed([press('K', { mod: true })])[0]!.action).toEqual({ type: 'palette' })
  })

  it('never captures keys while typing, except the palette', () => {
    for (const key of ['g', 'j', 'k', '/', '?', 'Enter', 'Escape', 'Backspace']) {
      const r = keymapStep(KEYMAP_IDLE, press(key, { typing: true }))
      expect(r.handled, key).toBe(false)
      expect(r.action, key).toBeNull()
    }
    expect(keymapStep(KEYMAP_IDLE, press('k', { typing: true, mod: true })).action).toEqual({ type: 'palette' })
  })

  it('stays out of the way while a modal is open', () => {
    expect(keymapStep(KEYMAP_IDLE, press('Escape', { modal: true })).handled).toBe(false)
    expect(keymapStep(KEYMAP_IDLE, press('j', { modal: true })).handled).toBe(false)
  })

  it('ignores Alt combos and unbound keys', () => {
    expect(keymapStep(KEYMAP_IDLE, press('g', { alt: true })).handled).toBe(false)
    expect(keymapStep(KEYMAP_IDLE, press('x')).handled).toBe(false)
    expect(keymapStep(KEYMAP_IDLE, press('G')).handled).toBe(false)
  })

  it('times a chord out and restarts from the new key', () => {
    let r = keymapStep(KEYMAP_IDLE, press('g', { at: 0 }))
    r = keymapStep(r.state, press('e', { at: CHORD_MS + 1 }))
    expect(r.action).toBeNull()
    r = keymapStep(KEYMAP_IDLE, press('g', { at: 0 }))
    r = keymapStep(r.state, press('j', { at: 10 }))
    expect(r.action).toEqual({ type: 'row', move: 'next' })
    expect(r.state).toEqual(KEYMAP_IDLE)
  })

  it('has no duplicate sequences and unique ids', () => {
    const seqs = KEYMAP.flatMap((b) => b.keys.map((k) => k.join(' ')))
    expect(new Set(seqs).size).toBe(seqs.length)
    expect(new Set(KEYMAP.map((b) => b.id)).size).toBe(KEYMAP.length)
  })

  it('labels keys for display', () => {
    expect(keyToken('k', true)).toBe('Mod+k')
    expect(keyLabel('Mod+k')).toBe('⌘K')
    expect(keyLabel('Mod+k', false)).toBe('Ctrl K')
    expect(keyLabel('ArrowDown')).toBe('↓')
    expect(sequenceLabel(['g', 'e'])).toBe('G E')
    expect(shortcutFor({ type: 'goto', section: 'evals' })).toBe('G V')
    expect(shortcutFor({ type: 'palette' }, false)).toBe('Ctrl K')
  })

  it('groups every binding for the overlay', () => {
    const groups = keymapGroups()
    expect(groups.map((g) => g.group)).toEqual(['General', 'Go to', 'Lists'])
    expect(groups.flatMap((g) => g.bindings)).toHaveLength(KEYMAP.length)
  })
})
