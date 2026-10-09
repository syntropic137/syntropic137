import { describe, expect, it } from 'vitest'
import {
  agentOf,
  filterWorkflows,
  parsePrompt,
  parseWorkflowFilter,
  phaseKitOf,
  phaseModelChip,
  phaseCostLabel,
  phaseShares,
  phaseUsage,
  phaseSlab,
  runSharePercent,
  runsLabel,
  workflowCategory,
  workflowSkillNames,
  workflowSkillRefs,
  workflowsSummary,
} from './index'

const rows = [
  { id: 'b', name: 'Beta', workflow_type: 'research', phase_count: 2, runs_count: 3 },
  { id: 'a', name: 'Alpha', workflow_type: 'review', phase_count: 1, runs_count: 0 },
  { id: 'c', name: 'Gamma', workflow_type: 'research', phase_count: 3, runs_count: 12 },
]

describe('workflows list', () => {
  it('filters by type, search and skills, sorts by runs then name', () => {
    expect(filterWorkflows(rows, { filter: 'all', sort: 'runs' }).map((r) => r.id)).toEqual(['c', 'b', 'a'])
    expect(filterWorkflows(rows, { filter: 'all', sort: 'name' }).map((r) => r.id)).toEqual(['a', 'b', 'c'])
    expect(filterWorkflows(rows, { filter: 'research', sort: 'runs' }).map((r) => r.id)).toEqual(['c', 'b'])
    expect(filterWorkflows(rows, { filter: 'all', sort: 'runs', search: 'alp' }).map((r) => r.id)).toEqual(['a'])
    const skillsOf = (id: string) => (id === 'b' ? ['x'] : id === 'a' ? [] : undefined)
    expect(filterWorkflows(rows, { filter: 'skills', sort: 'runs', skillsOf }).map((r) => r.id)).toEqual(['b'])
  })
  it('labels', () => {
    expect(runsLabel(0)).toBe('never run')
    expect(runsLabel(1)).toBe('1 run')
    expect(runsLabel(26)).toBe('26 runs')
    expect(runSharePercent(13, 26)).toBe(50)
    expect(runSharePercent(0, 0)).toBe(0)
    expect(workflowsSummary(12, 27, 'all')).toBe('Showing 12 of 27 workflows')
    expect(workflowsSummary(6, 6, 'skills')).toBe('Showing 6 of 6 workflows with skills')
    expect(parseWorkflowFilter('nope')).toBe('all')
    expect(parseWorkflowFilter('skills')).toBe('skills')
    expect(workflowCategory('IMPLEMENTATION')).toBe('Implementation')
    expect(workflowCategory('custom')).toBe('Custom')
  })
  it('collects unique skill names', () => {
    expect(workflowSkillNames([{ skills: [{ name: 'a' }, { source_url: 'gh/org/remote-herald@main' }] }, { skills: [{ name: 'a' }] }, {}])).toEqual(['a', 'remote-herald'])
    expect(workflowSkillRefs([{ skills: [{ name: 'a', source_url: 'https://github.com/o/r', version: 'abc' }] }, { skills: [{ name: 'a', source_url: 'x/y', version: 'z' }] }])).toEqual([
      { name: 'a', source: 'https://github.com/o/r', ref: 'abc' },
    ])
  })
})

describe('workflow detail', () => {
  it('reads the kit from a phase definition', () => {
    const kit = phaseKitOf({ phase_id: 'p', name: 'P', provider: 'claude', model_display: 'opus → claude-opus-5-5', allowed_tools: [], skills: [] })
    expect(kit.tools).toBe('default')
    expect(kit.skills).toBe('none')
    expect(kit.model).toEqual({ agent: 'Claude', agentKind: 'claude', resolution: 'opus → claude-opus-5-5' })
    const k2 = phaseKitOf({ phase_id: 'p', name: 'P', provider: 'codex', allowed_tools: ['Read'], skills: [{ name: 's', source_url: './skills/s', version: 'main' }] })
    expect(k2.tools).toEqual(['Read'])
    expect(k2.skills).toEqual([{ name: 's', source: './skills/s', ref: 'main' }])
    expect(agentOf({ provider: null, agent_type: '' }).agent).toBe('Agent')
    expect(phaseModelChip({ model: 'opus', model_display: 'default → opus → claude-opus-5-5' })).toBe('claude-opus-5-5')
    expect(phaseModelChip({ model: null })).toBe('default model')
  })
  it('sums phase shares across runs', () => {
    const s = phaseShares(['a', 'b'], [
      { phase_results: [{ phase_id: 'a', total_tokens: 100, cost_usd: '0.1' }, { phase_id: 'b', total_tokens: 300, cost_usd: 0.3 }] },
      { phase_results: [{ phase_id: 'a', total_tokens: 100, cost_usd: '0.1' }, { phase_id: 'zzz', total_tokens: 5, cost_usd: 1 }] },
    ])
    expect(s.a!.tokens).toBe(200)
    expect(s.a!.share).toBe(0.4)
    expect(s.b!.cost).toBeCloseTo(0.3)
    expect(phaseShares(['a'], []).a!.share).toBe(0)
  })
  it('reads per-phase usage from /metrics?workflow_id= phases, a running phase as a lower bound (live rows, 2026-10-09)', () => {
    const u = phaseUsage(['premise', 'fix', 'never_ran'], [
      { phase_id: 'premise', total_tokens: 431_048_980, cost_usd: '221.7891426', cost_in_progress: false },
      { phase_id: 'fix', total_tokens: 344_717_867, cost_usd: '267.0128436', cost_in_progress: true },
      { phase_id: 'fix_3', total_tokens: 9_723_683, cost_usd: '8.2363026', cost_in_progress: false },
    ])
    expect(u.premise).toMatchObject({ tokens: 431_048_980, partial: false })
    expect(phaseCostLabel(u.premise!)).toBe('$221.79')
    expect(phaseCostLabel(u.fix!)).toBe('≥$267.01')
    expect(u.never_ran).toMatchObject({ tokens: 0, share: 0, partial: false })
    expect(u.premise!.share + u.fix!.share).toBeCloseTo(1)
  })
  it('maps phases onto icon slabs', () => {
    expect([0, 1, 2].map((i) => phaseSlab(i, 3))).toEqual([0, 1, 2])
    expect(phaseSlab(0, 1)).toBe(0)
    expect(phaseSlab(4, 5)).toBe(2)
  })
  it('parses a prompt template', () => {
    const b = parsePrompt('You are a researcher.\n\n## Your Task\n$ARGUMENTS\n\n## How\n- one\n- two\nDone.')
    expect(b).toEqual([
      { kind: 'paragraph', text: 'You are a researcher.' },
      { kind: 'heading', text: 'Your Task' },
      { kind: 'argument', name: '$ARGUMENTS' },
      { kind: 'heading', text: 'How' },
      { kind: 'list', items: ['one', 'two'] },
      { kind: 'paragraph', text: 'Done.' },
    ])
    expect(parsePrompt('Task: {{task}}')).toEqual([{ kind: 'paragraph', text: 'Task: {{task}}' }])
    expect(parsePrompt('{{ task }}')).toEqual([{ kind: 'argument', name: 'task' }])
    expect(parsePrompt(null)).toEqual([])
  })
})
