import { describe, expect, it } from 'vitest'
import { buildPalette, filterPalette, pageForAgent } from './palette'

const help = { docs: 'https://docs.example', featureRequests: 'https://ideas.example', issues: 'https://issues.example' }
const sections = [
  { key: 'overview', label: 'Overview', href: '/' },
  { key: 'executions', label: 'Executions', href: '/executions' },
  { key: 'evals', label: 'Evals', href: '/evals' },
] as const

describe('buildPalette', () => {
  it('orders recent, actions, go to, help and drops empty groups', () => {
    const groups = buildPalette({ sections, help, executions: [{ id: 'abcdef123456', label: 'Research Workflow', status: 'failed' }] })
    expect(groups.map((g) => g.heading)).toEqual(['Recent executions', 'Actions', 'Go to', 'Help'])
    expect(groups[0]!.items[0]).toMatchObject({ meta: 'abcdef12', target: { kind: 'href', href: '/executions/abcdef123456' } })
  })

  it('takes go-to hints from the keymap', () => {
    const go = buildPalette({ sections, help }).find((g) => g.heading === 'Go to')!
    expect(go.items.map((i) => i.shortcut)).toEqual(['G O', 'G E', 'G V'])
    const ctrl = buildPalette({ sections, help, apple: false }).find((g) => g.heading === 'Help')!
    expect(ctrl.items[0]!.shortcut).toBe('?')
  })

  it('caps recent rows and encodes ids', () => {
    const rows = Array.from({ length: 9 }, (_, i) => ({ id: `s/${i}`, label: `S${i}` }))
    const g = buildPalette({ sections, help, sessions: rows, recent: 3 })[0]!
    expect(g.items).toHaveLength(3)
    expect(g.items[0]!.target).toEqual({ kind: 'href', href: '/sessions/s%2F0' })
  })

  it('links help to the three destinations', () => {
    const h = buildPalette({ sections, help }).find((g) => g.heading === 'Help')!
    expect(h.items.filter((i) => i.target.kind === 'external').map((i) => i.target)).toEqual([
      { kind: 'external', url: help.docs },
      { kind: 'external', url: help.featureRequests },
      { kind: 'external', url: help.issues },
    ])
  })

  it('ranks the best match first: "exec" puts Executions on top', () => {
    const rows = [{ id: 'e1', label: 'Research Workflow' }]
    const shown = filterPalette(buildPalette({ sections, help, executions: rows }), 'exec')
    expect(shown[0]!.heading).toBe('Go to')
    expect(shown[0]!.items[0]!.label).toBe('Executions')
    expect(shown.map((g) => g.heading)).toContain('Recent executions')
  })

  it('keeps board order with no query', () => {
    const all = buildPalette({ sections, help })
    expect(filterPalette(all, '  ').map((g) => g.heading)).toEqual(all.map((g) => g.heading))
  })
})

describe('pageForAgent', () => {
  it('writes title, url, trail and squashed text', () => {
    const out = pageForAgent({ title: 'Execution', url: 'http://x/executions/1', crumbs: ['Executions', 'Execution'], text: '  Hello   world \n\n\n Cost  $1 ' })
    expect(out).toBe('Syntropic137 page: Execution\nURL: http://x/executions/1\nTrail: Executions / Execution\n\nHello world\nCost $1\n')
  })

  it('truncates long pages', () => {
    const out = pageForAgent({ title: 't', url: 'u', crumbs: [], text: 'a'.repeat(50) }, 10)
    expect(out).toContain('[truncated at 10 characters]')
    expect(out).not.toContain('Trail:')
  })
})

describe('build in the palette', () => {
  it('adds a Version row to Help only once the build is known', () => {
    const help = (version?: string | null) => buildPalette({ sections, help: { docs: 'd', featureRequests: 'f', issues: 'i' }, version }).find((g) => g.heading === 'Help')!
    expect(help(null).items.map((i) => i.id)).not.toContain('help-version')
    expect(help('v0.33.2b23').items.at(-1)).toMatchObject({ id: 'help-version', label: 'Version', meta: 'v0.33.2b23', target: { kind: 'command', command: 'copy-build' } })
    expect(filterPalette(buildPalette({ sections, help: { docs: 'd', featureRequests: 'f', issues: 'i' }, version: 'v1' }), 'version')[0]!.items[0]!.id).toBe('help-version')
  })
  it('puts the build line under the URL in the agent block', () => {
    const out = pageForAgent({ title: 'Overview', url: 'u', crumbs: [], text: 'x', build: 'Build: API v0.33.2b23' })
    expect(out).toBe('Syntropic137 page: Overview\nURL: u\nBuild: API v0.33.2b23\n\nx\n')
  })
})
