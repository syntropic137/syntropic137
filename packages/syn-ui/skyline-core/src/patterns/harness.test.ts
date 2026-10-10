import { describe, expect, it } from 'vitest'
import { harnessLanes, harnessLook, harnessProvider } from './index'

describe('harness chip and lanes (Landing pillar 02)', () => {
  it('maps providers to harness tokens', () => {
    expect(harnessProvider('Claude Code')).toBe('claude')
    expect(harnessProvider('codex')).toBe('codex')
    expect(harnessProvider('openai')).toBe('codex')
    expect(harnessProvider('gemini')).toBe('other')
    expect(harnessLook('claude')).toMatchObject({ name: 'Claude Code', token: '--sky-harness-claude', gradient: '--sky-harness-claude-gradient' })
    expect(harnessLook('codex').token).toBe('--sky-harness-codex')
    expect(harnessLook('gemini')).toMatchObject({ provider: 'other', name: 'gemini', token: '--ds-color-text-subtle' })
  })

  it('lays the board phases out in one lane per harness', () => {
    const lanes = harnessLanes([
      { name: 'plan', provider: 'claude', span: 2 },
      { name: 'implement', provider: 'codex', span: 3 },
      { name: 'fix', provider: 'claude', span: 2 },
      { name: 'review', provider: 'codex', span: 2 },
    ])
    expect(lanes.map((l) => l.label)).toEqual(['claude', 'codex'])
    // harness_visual(): cells_c and cells_x.
    expect(lanes[0]!.cells.map((c) => [c.name, c.span, c.on])).toEqual([
      ['plan', 2, true],
      ['', 3, false],
      ['fix', 2, true],
      ['', 2, false],
    ])
    expect(lanes[1]!.cells.map((c) => [c.name, c.span, c.on])).toEqual([
      ['', 2, false],
      ['implement', 3, true],
      ['', 2, false],
      ['review', 2, true],
    ])
    expect(lanes.map((l) => l.summary)).toEqual(['claude runs plan and fix', 'codex runs implement and review'])
  })

  it('defaults bad spans to 1 and keeps unknown harnesses apart', () => {
    const lanes = harnessLanes([
      { name: 'a', provider: 'gemini', span: 0 },
      { name: 'b', provider: 'llama' },
    ])
    expect(lanes).toHaveLength(2)
    expect(lanes[0]!.cells.map((c) => [c.span, c.on])).toEqual([
      [1, true],
      [1, false],
    ])
    expect(harnessLanes([])).toEqual([])
  })
})
