import { describe, expect, it } from 'vitest'
import { buildRuleClauses } from '../../patterns/rule'
import { filterTriggers, groupTriggersByRepo, normalizeConditions, triggerCaps, triggerLogLine, triggerRuleInput, triggerSummary, triggerTitle } from './index'

const t = (o: Partial<Parameters<typeof triggerTitle>[0]> & Record<string, unknown> = {}) => ({
  trigger_id: 'tr-1',
  name: 'Self heal',
  event: 'check_run.completed',
  repository: 'syntropic137/syntropic137',
  workflow_id: 'self-heal',
  workflow_name: 'Self-Heal PR',
  status: 'active',
  fire_count: 0,
  ...o,
})

describe('triggers', () => {
  it('titles like the React app', () => {
    expect(triggerTitle(t())).toBe('check_run.completed → Self-Heal PR')
    expect(triggerTitle(t({ workflow_name: undefined }))).toBe('Self heal')
  })
  it('filters and groups', () => {
    const list = [t(), t({ trigger_id: 'b', repository: 'a/b', status: 'paused', event: 'issue_comment.created' })]
    expect(filterTriggers(list, { status: 'paused' }).map((x) => x.trigger_id)).toEqual(['b'])
    expect(filterTriggers(list, { q: 'ISSUE' }).length).toBe(1)
    expect(filterTriggers(list, { status: 'all' }).length).toBe(2)
    expect(groupTriggersByRepo(list).map((g) => g.repo)).toEqual(['a/b', 'syntropic137/syntropic137'])
    expect(triggerSummary(list)).toBe('2 rules across 2 repos, 1 paused.')
    expect(triggerSummary([t(), t()])).toBe('2 rules across 1 repo, all active.')
    expect(triggerSummary([])).toBe('No rules yet.')
  })
  it('normalizes conditions in both shapes', () => {
    expect(normalizeConditions([{ field: 'a', operator: 'not_empty' }, { nope: 1 }])).toEqual([{ field: 'a', operator: 'not_empty', value: null }])
    expect(normalizeConditions({ draft: false, base: 'main' })).toEqual([
      { field: 'draft', operator: 'eq', value: 'false' },
      { field: 'base', operator: 'eq', value: 'main' },
    ])
    expect(normalizeConditions(null)).toEqual([])
  })
  it('maps config to caps', () => {
    expect(triggerCaps({ max_attempts: 3, daily_limit: 20, debounce_seconds: 0, cooldown_seconds: 300 })).toEqual([
      { value: '3', label: 'max attempts' },
      { value: '20', label: 'runs per day' },
      { value: '300s', label: 'cooldown' },
      { value: '0s', label: 'debounce' },
    ])
    expect(triggerCaps({ max_fires_per_day: 5 })).toEqual([{ value: '5', label: 'runs per day' }])
  })
  it('builds a full rule sentence', () => {
    const input = triggerRuleInput(
      { ...t(), conditions: [{ field: 'check_run.conclusion', operator: 'eq', value: 'failure' }], input_mapping: { branch: 'x.ref' }, config: null },
      triggerLogLine(0, 0),
    )
    const keys = buildRuleClauses(input).map((c) => c.key)
    expect(keys).toEqual(['when', 'if', 'then', 'log'])
    expect(input.workflowHref).toBe('/workflows/self-heal')
    expect(triggerLogLine(3, 2).text).toBe('Fired 3 times')
  })
})
