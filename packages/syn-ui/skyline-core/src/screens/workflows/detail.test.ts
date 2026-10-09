import { describe, expect, it } from 'vitest'
import { buildAgentPrompt } from '../../patterns/agentPrompt'
import {
  canStartRun,
  consumesTask,
  latestOutputOf,
  latestOutputsByPhase,
  parseRunFilter,
  runDurationMs,
  runFilterOf,
  runsSummary,
  runsView,
  workflowFigures,
  workflowPromptSpec,
  workflowTags,
  workflowTotals,
} from './detail'

const NOW = Date.parse('2026-10-08T12:00:00Z')
const run = (id: string, status: string, hoursAgo: number, seconds = 227, tokens = 1000, cost: string | number = '0.21') => ({
  workflow_execution_id: id,
  status,
  started_at: new Date(NOW - hoursAgo * 3_600_000).toISOString(),
  completed_at: status === 'running' ? null : new Date(NOW - hoursAgo * 3_600_000 + seconds * 1000).toISOString(),
  total_tokens: tokens,
  total_cost_usd: cost,
})

describe('workflow header', () => {
  it('sums tokens and spend from the run list, and waits for it', () => {
    const runs = [run('a', 'completed', 1, 10, 396_791, '0.2162'), run('b', 'cancelled', 2, 10, 156_600, 0.17)]
    expect(workflowTotals(12, runs)).toEqual({ runs: 12, tokens: 553_391, cost: 0.3862 })
    expect(workflowFigures(3, 12, runs).map((f) => f.label)).toEqual(['Runs', 'Phases', 'Tokens', 'Spend'])
    expect(workflowFigures(3, 12, runs)[3]!.value).toBe('$0.3862')
    expect(workflowFigures(3, 12, null).slice(2).map((f) => f.value)).toEqual(['—', '—'])
  })

  it('builds the agent prompt from the declared inputs and phases', () => {
    const spec = workflowPromptSpec({
      id: 'research-workflow',
      name: 'Research Workflow',
      phases: [{ name: 'Research' }, { name: 'Synthesize' }, { name: 'Report' }],
      input_declarations: [{ name: 'task', description: 'What to do', required: true }, { name: 'topic', required: false }],
    })
    const text = buildAgentPrompt(spec)
    expect(text).toContain('syn workflow run research-workflow --task "<what to do>"')
    expect(text).toContain('- topic (optional): add --input topic=<topic>.')
    expect(text).toContain('It runs 3 phases in order: Research, Synthesize, Report.')
  })

  it('offers --task even when no input is declared', () => {
    expect(workflowPromptSpec({ id: 'w', name: 'W', phases: [] }).inputs?.[0]?.name).toBe('task')
  })

  it('tags type, classification and repo needs', () => {
    expect(workflowTags({ workflow_type: 'research', classification: 'standard', requires_repos: false })).toEqual(['research', 'standard', 'no repos'])
    expect(workflowTags({ workflow_type: 'implementation', requires_repos: true, tags: ['sdlc'] })).toEqual(['implementation', 'needs repos', 'sdlc'])
  })

  it('knows when a task reaches a phase and when the form can start a run', () => {
    expect(consumesTask([{ prompt_template: 'Do it.\n$ARGUMENTS' }])).toBe(true)
    expect(consumesTask([{ prompt_template: 'Topic {{ task }}' }])).toBe(true)
    expect(consumesTask([{ prompt_template: 'fixed prompt' }, { prompt_template: null }])).toBe(false)
    const decls = [{ name: 'task', required: true }, { name: 'repo', required: true, default: null }, { name: 'depth', required: true, default: '2' }]
    expect(canStartRun(decls, '', { repo: 'x' })).toBe(false)
    expect(canStartRun(decls, 'go', {})).toBe(false)
    expect(canStartRun(decls, 'go', { repo: 'x' })).toBe(true)
  })
})

describe('latest outputs', () => {
  it('reads an artifact as the board row, and null as no output yet', () => {
    expect(latestOutputOf({ id: 'art-1', title: 'deliverable.md', artifact_type: 'report', size_bytes: 2970, execution_id: 'exec-66e14f235942' })).toEqual({
      artifactId: 'art-1',
      title: 'deliverable.md',
      meta: '2.9 KB · exec-66e14f23',
      executionId: 'exec-66e14f235942',
    })
    expect(latestOutputOf({ id: 'a', title: null, artifact_type: 'json', size_bytes: 10 })?.title).toBe('json')
    expect(latestOutputsByPhase([{ phase_id: 'research', artifact: null }, { phase_id: 'report' }])).toEqual({ research: null, report: null })
  })
})

describe('runs list', () => {
  const runs = [
    run('r1', 'running', 0.1),
    run('c1', 'completed', 3, 227),
    run('f1', 'failed', 30, 90),
    run('x1', 'cancelled', 24 * 40, 56),
    run('q1', 'queued', 0.2),
    run('i1', 'interrupted', 5),
  ]

  it('parses the status filter and maps statuses to chips', () => {
    expect(parseRunFilter('failed')).toBe('failed')
    expect(parseRunFilter('nope')).toBe('all')
    expect(runFilterOf('queued')).toBe('running')
    expect(runFilterOf('interrupted')).toBe('cancelled')
    expect(runFilterOf('mystery')).toBeNull()
  })

  it('windows, counts, filters and pages, newest first', () => {
    const all = runsView(runs, { status: 'all', window: 'all', page: 1, pageSize: 4, now: NOW })
    expect(all.counts).toEqual({ all: 6, running: 2, completed: 1, failed: 1, cancelled: 2 })
    expect(all.rows.map((r) => r.workflow_execution_id)).toEqual(['r1', 'q1', 'c1', 'i1'])
    expect(all.pageCount).toBe(2)
    expect(runsView(runs, { status: 'all', window: 'all', page: 9, pageSize: 4, now: NOW }).page).toBe(2)
    const day = runsView(runs, { status: 'cancelled', window: '24h', page: 1, pageSize: 4, now: NOW })
    expect(day.inWindow).toBe(4)
    expect(day.rows.map((r) => r.workflow_execution_id)).toEqual(['i1'])
    expect(runsSummary(all, 4, 'all')).toBe('Showing 1-4 of 6 runs')
    expect(runsSummary(day, 4, 'cancelled')).toBe('Showing 1-1 of 1 cancelled runs')
    expect(runsSummary({ page: 1, matched: 0, rows: [] }, 4, 'all')).toBe('No runs')
  })

  it('measures a running run to now and an undated one as unknown', () => {
    expect(runDurationMs(run('c', 'completed', 1, 227), NOW)).toBe(227_000)
    expect(runDurationMs(run('r', 'running', 1), NOW)).toBe(3_600_000)
    expect(runDurationMs({ started_at: null }, NOW)).toBeNull()
  })
})
