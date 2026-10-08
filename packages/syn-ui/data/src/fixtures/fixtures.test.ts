import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { configureClient } from '../client'
import { ApiError } from '../client/errors'
import {
  getSessionInventory,
  getArtifact,
  getContributionHeatmap,
  getEval,
  getExecution,
  getSession,
  getTrigger,
  getWorkflow,
  listArtifacts,
  listEvals,
  listEvalRuns,
  listExecutions,
  listRepos,
  lookUpAppAccess,
  listSessions,
  listTriggers,
  listWorkflowRuns,
  listWorkflows,
  getMetrics,
  getCostSummary,
  getToolTimeline,
  getEvalTrend,
  getWorkflowTrend,
} from '../index'
import { RUNS, matchFixture } from './index'

beforeEach(() => {
  configureClient({ fixtures: true, fixtureLatencyMs: 0 })
})
afterEach(() => {
  configureClient({ fixtures: false, fixtureLatencyMs: 120 })
})

describe('fixture router', () => {
  it('matches params and methods', () => {
    expect(matchFixture('GET', '/workflows/research-workflow')?.params).toEqual({ workflowId: 'research-workflow' })
    expect(matchFixture('POST', '/workflows/research-workflow')).toBeNull()
    expect(matchFixture('GET', '/nope')).toBeNull()
  })
  it('404s for unknown paths and ids', async () => {
    await expect(getWorkflow('missing')).rejects.toBeInstanceOf(ApiError)
    await expect(getExecution('missing')).rejects.toMatchObject({ status: 404 })
  })
})

describe('every screen has data in fixtures mode', () => {
  it('workflows', async () => {
    const list = await listWorkflows()
    expect(list.total).toBeGreaterThan(5)
    const wf = await getWorkflow('research-workflow')
    expect(wf.phases.map((p) => p.name)).toEqual(['Research', 'Synthesize', 'Report'])
    expect((await listWorkflowRuns('research-workflow')).length).toBeGreaterThan(3)
    expect((await listWorkflows({ page_size: 100 })).total).toBe(27)
    const skills = await getWorkflow('skills-matrix')
    expect(skills.phases[1]?.skills?.map((s) => s.name)).toEqual(['vendored-scribe', 'remote-herald'])
    expect((await getWorkflow('code-review')).runs_count).toBe(0)
  })
  it('executions, filtered and paged, with consistent detail', async () => {
    const page = await listExecutions({ page: 1, page_size: 5, statuses: ['failed'] })
    expect(page.executions.every((e) => e.status === 'failed')).toBe(true)
    expect(page.status_counts?.completed).toBeGreaterThan(0)
    const all = await listExecutions({ page: 1, page_size: 100 })
    expect(all.total).toBe(RUNS.length)
    const first = all.executions[0]!
    const detail = await getExecution(first.workflow_execution_id)
    expect(detail.workflow_name).toBe(first.workflow_name)
    expect(detail.phases.length).toBe(first.total_phases)
  })
  it('execution board run, time window and session inventory', async () => {
    const board = await getExecution(RUNS[2]!.id)
    expect(board.task).toBe('one sentence on sorting')
    expect(board.phases.map((p) => p.name)).toEqual(['Discovery Phase', 'Deep Dive Analysis', 'Synthesis & Documentation'])
    expect(board.total_cache_read_tokens).toBe(313_560)
    const recent = await listExecutions({ page: 1, page_size: 50, started_after: new Date(Date.UTC(2026, 9, 7)).toISOString() })
    expect(recent.total).toBeLessThan(RUNS.length)
    const inv = await getSessionInventory(RUNS[2]!.id)
    expect(inv.summary.platform_sessions).toBe(3)
    expect(inv.summary.complete).toBe(false)
  })
  it('sessions link back to their execution', async () => {
    const list = await listSessions({ page: 1, page_size: 10 })
    const s = await getSession(list.sessions![0]!.id)
    expect(s.execution_id).toBeTruthy()
    expect(s.operations.length).toBeGreaterThan(0)
    expect((await getToolTimeline(s.id)).total_executions).toBeGreaterThan(0)
  })
  it('evals, artifacts, triggers, repos, overview', async () => {
    const evals = await listEvals()
    expect(evals.total).toBe(24)
    expect((await getEval(evals.evals[0]!.eval_id)).tags.some((t) => t.startsWith('case:'))).toBe(true)
    expect((await listEvals({ tag: 'case:codex-cost-limit' })).total).toBe(4)
    const opus = await listEvalRuns('eval-shared-esp-stream-1')
    expect(opus.total).toBe(5)
    expect(new Set(opus.items.map((r) => r.workflow_version))).toEqual(new Set(['v1', 'v2']))
    const arts = await listArtifacts({ page: 1, page_size: 10 })
    expect(arts.artifacts.length).toBeGreaterThan(0)
    expect((await getArtifact(arts.artifacts[0]!.id, true)).content).toContain('#')
    const triggers = await listTriggers()
    expect((await getTrigger(triggers.triggers[0]!.trigger_id)).conditions).toBeTruthy()
    expect((await listRepos()).length).toBe(4)
    expect((await lookUpAppAccess()).repos.map((r) => r.fullName)).toContain('syntropic137/homelab-infra')
    const heat = await getContributionHeatmap()
    expect(heat.days?.find((d) => d.date === '2026-08-28')?.count).toBe(43)
    expect((await getMetrics()).total_workflows).toBeGreaterThan(0)
    expect((await getCostSummary()).total_cost_usd).toBeGreaterThan(0)
  })
  it('returns copies, so callers cannot edit the store', async () => {
    const a = await getWorkflow('research-workflow')
    a.name = 'changed'
    expect((await getWorkflow('research-workflow')).name).toBe('Research Workflow')
  })
})

describe('trend fixtures (Eval and Workflows boards)', () => {
  it('serves the Eval board sample: 28 runs, four verifiers, one judge, v2 from day 18', async () => {
    const rows = await getEvalTrend('eval-shared-esp-stream-4')
    expect(rows).toHaveLength(28)
    expect(new Set(rows.map((r) => r.verifier_model)).size).toBe(4)
    expect(new Set(rows.flatMap((r) => (r.judge_model ? [r.judge_model] : [])))).toEqual(new Set(['claude-opus-5-5']))
    expect(rows[0]).toMatchObject({ date: '2026-09-08T09:00:00.000Z', verifier_model: 'claude-opus-5-5', score: 82, verdict: 'PASS', cost_usd: 1.21, duration_seconds: 452, tokens: 134444 })
    expect(rows.at(-1)).toMatchObject({ verifier_model: 'gpt-5.6-terra', score: null, verdict: null })
    expect(rows.filter((r) => r.definition_version === 'v2').every((r) => r.definition_changed_at === '2026-09-26T00:00:00.000Z')).toBe(true)
    await expect(getEvalTrend('missing')).rejects.toMatchObject({ status: 404 })
  })
  it('serves one workflow row per run with phase durations', async () => {
    const rows = await getWorkflowTrend('research-workflow')
    expect(rows).toHaveLength((await listWorkflowRuns('research-workflow')).length)
    expect(rows[0]!.phase_durations.map((p) => p.phase_name)).toEqual(['Research', 'Synthesize', 'Report'])
    expect(rows.find((r) => r.status === 'running')?.duration_seconds).toBeNull()
    expect(await getWorkflowTrend('code-review')).toEqual([])
  })
})
