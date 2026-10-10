import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { configureClient } from '../client'
import { ApiError } from '../client/errors'
import {
  getSessionInventory,
  getSessionInventoryNode,
  getSessionInventoryPage,
  getLocalTranscript,
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
  getWorkflowLatestOutputs,
  getShippedMetrics,
} from '../index'
import { RUNS, matchFixture } from './index'
import { EVALS } from './evals'

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
    // Every eval run is an execution too, as on the API.
    expect(all.total).toBe(RUNS.length + EVALS.reduce((n, e) => n + e.runs.length, 0))
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
    // Windows are relative: "the last 24h" asked any day means the 24h before FIXTURE_NOW.
    const dayAgo = new Date(Date.now() - 86_400_000).toISOString()
    const recent = await listExecutions({ page: 1, page_size: 50, started_after: dayAgo })
    expect(recent.total).toBeLessThan(RUNS.length)
    expect(recent.total).toBeGreaterThanOrEqual(5)
    // in_eval narrows to runs that belong to an eval; each carries its eval link (feedback 4df2bfc9).
    const evals = await listExecutions({ page: 1, page_size: 100, in_eval: true })
    expect(evals.total).toBeGreaterThan(0)
    expect(evals.executions.every((e) => e.eval?.eval_id)).toBe(true)
    const allSessions = await listSessions({ page: 1, page_size: 100 })
    const recentSessions = await listSessions({ page: 1, page_size: 100, started_after: dayAgo })
    expect(recentSessions.total).toBeGreaterThanOrEqual(5)
    expect(recentSessions.total).toBeLessThanOrEqual(allSessions.total)
    const inv = await getSessionInventory(RUNS[2]!.id)
    expect(inv.summary.platform_sessions).toBe(3)
    expect(inv.summary.complete).toBe(false)
  })
  it('inventory pages, nodes and transcripts 404 like the API when there is no snapshot', async () => {
    const id = RUNS[2]!.id
    for (const call of [
      () => getSessionInventoryPage(id, 'snap', 'node', null),
      () => getSessionInventoryNode(id, 'snap', 'node-1'),
      () => getLocalTranscript(id, 'claude', 'native-1', 'rev-1'),
    ]) {
      await expect(call()).rejects.toMatchObject({ status: 404 })
    }
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
    expect(evals.total).toBe(29)
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
    // /metrics?workflow_id= counts every phase; /workflows/{id}/runs drops failed-phase usage, as the API does (#1843).
    const wm = await getMetrics('skills-matrix')
    const runs = await listWorkflowRuns('skills-matrix')
    const listed = (await listExecutions({ q: 'skills-matrix', page: 1, page_size: 50 })).executions.filter((e) => e.workflow_id === 'skills-matrix')
    const failed = runs.find((r) => r.status === 'failed')!
    const failedListed = listed.find((e) => e.workflow_execution_id === failed.workflow_execution_id)!
    expect(failedListed.total_tokens).toBeGreaterThan(failed.total_tokens ?? 0)
    expect(wm.total_tokens).toBe(listed.reduce((n, e) => n + (e.total_tokens ?? 0), 0))
    expect(new Set(wm.phases.map((p) => p.phase_id)).size).toBe(wm.phases.length)
    expect((await getCostSummary()).total_cost_usd).toBeGreaterThan(0)
  })
  it('returns copies, so callers cannot edit the store', async () => {
    const a = await getWorkflow('research-workflow')
    a.name = 'changed'
    expect((await getWorkflow('research-workflow')).name).toBe('Research Workflow')
  })
})

describe('trend fixtures (Eval and Workflows boards, PR #1800 shape)', () => {
  it('serves the Eval board sample newest first: 28 runs, four verifiers, one judge, v2 from day 18', async () => {
    const res = await getEvalTrend('eval-shared-esp-stream-4')
    expect(res).toMatchObject({ eval_id: 'eval-shared-esp-stream-4', total: 28, definition_version: '2', definition_changed_at: '2026-09-26T00:00:00.000Z' })
    const rows = res.items
    expect(rows).toHaveLength(28)
    expect(new Set(rows.map((r) => r.verifier_model)).size).toBe(4)
    expect(new Set(rows.flatMap((r) => (r.judge_model ? [r.judge_model] : [])))).toEqual(new Set(['claude-opus-5-5']))
    expect(rows.at(-1)).toMatchObject({ date: '2026-09-08T09:00:00.000Z', verifier_model: 'claude-opus-5-5', score: 82, verdict: 'PASS', cost_display: '$1.21', duration_seconds: 452, duration_display: '7m 32s', tokens: 134444, eval_definition_version: '1' })
    expect(rows[0]).toMatchObject({ verifier_model: 'gpt-5.6-terra', score: null, verdict: null, eval_definition_version: '2' })
    expect(res.definition_changes.map((c) => c.kind)).toEqual(['created', 'updated'])
    await expect(getEvalTrend('missing')).rejects.toMatchObject({ status: 404 })
  })
  it('serves one workflow row per run, newest first, with phase durations', async () => {
    const res = await getWorkflowTrend('research-workflow')
    expect(res.items).toHaveLength((await listWorkflowRuns('research-workflow')).length)
    expect(res.items[0]!.date! >= res.items.at(-1)!.date!).toBe(true)
    expect(res.items[0]!.phase_durations.map((p) => p.phase_name)).toEqual(['Research', 'Synthesize', 'Report'])
    expect(res.items.find((r) => r.status === 'running')?.duration_seconds).toBeNull()
    expect((await getWorkflowTrend('code-review')).items).toEqual([])
  })
})


describe('paginate honours the API page-size limit', () => {
  it('rejects page_size above MAX_PAGE_SIZE with the API\'s 422 shape', async () => {
    const { paginate } = await import('./seed')
    const { MAX_PAGE_SIZE } = await import('../client/listQuery')
    const { ApiError } = await import('../client/errors')
    const rows = Array.from({ length: 3 }, (_, i) => i)
    expect(paginate(rows, new URLSearchParams(`page_size=${MAX_PAGE_SIZE}`)).page_size).toBe(MAX_PAGE_SIZE)
    let caught: unknown
    try { paginate(rows, new URLSearchParams(`page_size=${MAX_PAGE_SIZE + 1}`)) } catch (e) { caught = e }
    expect(caught).toBeInstanceOf(ApiError)
    expect((caught as InstanceType<typeof ApiError>).status).toBe(422)
  })
})

describe('workflow latest outputs (Workflow board, api-gaps shape)', () => {
  it('returns every phase in order with its newest artifact, null when none', async () => {
    const res = await getWorkflowLatestOutputs('research-workflow')
    expect(res.workflow_id).toBe('research-workflow')
    expect(res.phases.map((p) => p.phase_name)).toEqual(['Research', 'Synthesize', 'Report'])
    const report = res.phases[2]!.artifact!
    expect(report).toMatchObject({ workflow_id: 'research-workflow', phase_id: 'report', title: 'report.md' })
    expect(RUNS.some((r) => r.id === report.execution_id)).toBe(true)
    expect((await getWorkflowLatestOutputs('code-review')).phases.every((p) => p.artifact === null)).toBe(true)
    await expect(getWorkflowLatestOutputs('missing')).rejects.toMatchObject({ status: 404 })
  })
})

describe('shipped metrics (Main board "Shipped by agents")', () => {
  afterEach(() => {
    delete (globalThis as { synFixtureShippedUnavailable?: unknown }).synFixtureShippedUnavailable
  })
  it('serves the board sample for 14 days, series summing to the totals', async () => {
    const res = await getShippedMetrics({ days: 14 })
    expect(res.window.days).toBe(14)
    expect(res.window.to.slice(0, 10)).toBe('2026-10-08')
    expect([res.commits, res.prs_opened, res.prs_merged, res.merge_rate, res.repos_touched].map((m) => [m?.total, m?.delta_display])).toEqual([
      [1204, '+38%'], [73, '+24%'], [61, '+27%'], [84, '+5 pts'], [9, '+3'],
    ])
    for (const m of [res.commits, res.prs_opened, res.prs_merged]) {
      expect(m!.series).toHaveLength(14)
      expect(m!.series.reduce((a, p) => a + p.value, 0)).toBe(m!.total)
    }
    expect(res.commits!.series[0]!.date).toBe('2026-09-25')
    expect(res.by_workflow.reduce((a, w) => a + w.commits, 0)).toBe(1204)
    expect(res.repos).toHaveLength(9)
  })
  it('scales to 7 and 30 days and filters by workflow', async () => {
    expect((await getShippedMetrics({ days: 30 })).commits!.series).toHaveLength(30)
    expect((await getShippedMetrics({ days: 7, workflow_id: 'pr-review' })).by_workflow.map((w) => w.workflow_id)).toEqual(['pr-review'])
  })
  it('the test hook nulls a tile with a reason', async () => {
    ;(globalThis as { synFixtureShippedUnavailable?: unknown }).synFixtureShippedUnavailable = ['prs_opened']
    const res = await getShippedMetrics({ days: 7 })
    expect(res.prs_opened).toBeNull()
    expect(res.reasons?.prs_opened).toMatch(/pull requests/)
  })
})
