import type { InventoryStatus } from '../resources/sessionInventory'
import type { ExecutionDetailResponse, ExecutionListResponse, PhaseExecutionDetail } from '../types'
import { type CatalogRun, RUNS, phaseRuns, runOf, workflowOf } from './catalog'
import { type FixtureRoute, notFound, route } from './define'
import { costDisplay, countBy, durationDisplay, fakeId, filterList, fixtureWindowStart, paginate, tokensDisplay } from './seed'

/**
 * Board-exact phases for the canonical Research run (Execution board,
 * exec-66e14f23): names, durations, token splits and costs as drawn.
 * Indexed by the run's position in RUNS.
 */
interface PhaseOverride {
  name: string
  seconds: number
  input: number
  cacheWrite: number
  cacheRead: number
  output: number
  cost: number
  requested: string
}

const CANONICAL_RUN = 2
const CANONICAL_PHASES: PhaseOverride[] = [
  { name: 'Discovery Phase', seconds: 24.3, input: 25, cacheWrite: 31_442, cacheRead: 60_160, output: 1_801, cost: 0.0557, requested: 'haiku' },
  { name: 'Deep Dive Analysis', seconds: 118.9, input: 34, cacheWrite: 13_074, cacheRead: 120_987, output: 9_823, cost: 0.0798, requested: 'haiku' },
  { name: 'Synthesis & Documentation', seconds: 80.6, input: 34, cacheWrite: 20_368, cacheRead: 132_413, output: 6_630, cost: 0.0745, requested: 'haiku' },
]

/** The task each run was dispatched with; board copy for the canonical run. */
const TASKS: Record<string, string> = {
  'research-workflow': 'Survey how agent harnesses record token usage and summarise the differences.',
  'pr-review': 'Review the open pull request and post findings as review comments.',
  'starter-pr-review': 'Review the latest pull request.',
  'codex-delegates-to-claude': 'Plan a refactor of the session projection and hand the edit to Claude.',
  'claude-delegates-to-codex': 'Plan a fix for the flaky retry test and hand the edit to Codex.',
  'skills-matrix': 'Load every declared skill once and record which resolved.',
  'skill-probe': 'Check that the pinned skills resolve inside the workspace.',
  'starter-research': 'Research the trade-offs of SSE versus WebSockets for live dashboards.',
  'subagent-observability-demo': 'Spawn two subagents and collect their lifecycle events.',
  'codex-bridge-demo': 'Say hello through the Codex bridge.',
  'multi-agent': 'Plan and implement a palindrome checker with tests.',
}

const taskOf = (r: CatalogRun) => (RUNS.indexOf(r) === CANONICAL_RUN ? 'one sentence on sorting' : (TASKS[r.workflowId] ?? 'Run the workflow.'))

type ExecutionListItem = ExecutionListResponse['executions'][number]

export function executionListItem(r: CatalogRun): ExecutionListItem {
  const w = workflowOf(r.workflowId)
  const total = w?.phases.length ?? 0
  const phases = phaseRuns(r)
  const sum = (k: 'input' | 'output' | 'cacheWrite' | 'cacheRead') => phases.reduce((n, p) => n + p.tokens[k], 0)
  return {
    workflow_execution_id: r.id,
    workflow_id: r.workflowId,
    workflow_name: w?.name ?? r.workflowId,
    status: r.status,
    started_at: r.startedAt,
    completed_at: r.status === 'running' ? null : new Date(Date.parse(r.startedAt) + r.seconds * 1000).toISOString(),
    completed_phases: r.done,
    total_phases: total,
    phase_progress: {
      completed: r.done,
      skipped: 0,
      possible: total,
      remaining_possible: total - r.done,
      percent: total ? Math.round((r.done / total) * 100) : 0,
      display: `${r.done} of ${total}`,
    },
    total_tokens: r.tokens,
    total_tokens_display: tokensDisplay(r.tokens),
    total_input_tokens: sum('input'),
    total_output_tokens: sum('output'),
    total_cache_creation_tokens: sum('cacheWrite'),
    total_cache_read_tokens: sum('cacheRead'),
    total_cost_usd: r.cost.toFixed(6),
    total_cost_display: costDisplay(r.cost),
    unpriced_observation_count: 0,
    duration_seconds: r.seconds,
    duration_display: durationDisplay(r.seconds),
    tool_call_count: r.done * 14,
    error_message: r.status === 'failed' ? 'Phase exited with a non-zero status' : null,
    failure_classification: 'unclassified',
    repos: r.repo ? [r.repo] : [],
    tags: [],
    repos_display: r.repo ? r.repo.replace('https://github.com/', '') : null,
    start_queue: null,
  }
}

function phaseDetail(r: CatalogRun): PhaseExecutionDetail[] {
  const canonical = RUNS.indexOf(r) === CANONICAL_RUN
  const legacy = Date.parse(r.startedAt) < Date.parse(RUNS[1]!.startedAt) // older runs predate start pins
  return phaseRuns(r).map((p): PhaseExecutionDetail => {
    const o = canonical ? CANONICAL_PHASES[p.index] : undefined
    const base = baseDetail(p)
    if (!legacy && p.startedAt) {
      base.start_pins_status = 'recorded'
      base.pinned_at_start = {
        provider: p.phase.provider,
        requested_model: p.phase.model,
        allowed_tools: p.phase.provider === 'claude' ? ['Read', 'Glob', 'Grep', 'Bash', 'WebSearch'] : [],
        skills: p.phase.id === 'research' ? [{ name: 'doc-coauthoring', version: 'main', resolved_sha: 'db8ee61a0c3f2b7e', source_url: 'anthropics/skills' }] : [],
      }
    } else base.start_pins_status = 'not_recorded'
    if (!o) return base
    return {
      ...base,
      name: o.name,
      input_tokens: o.input,
      output_tokens: o.output,
      cache_creation_tokens: o.cacheWrite,
      cache_read_tokens: o.cacheRead,
      duration_seconds: o.seconds,
      cost_usd: o.cost,
      model: null,
      requested_model: o.requested,
      model_display: `unknown (requested: ${o.requested})`,
      cost_by_model: { unattributed: o.cost.toFixed(6) },
    }
  })
}

function baseDetail(p: ReturnType<typeof phaseRuns>[number]): PhaseExecutionDetail {
  return {
    phase_id: p.phase.id,
    name: p.phase.name,
    status: p.status,
    session_id: p.sessionId,
    agent_session_id: p.sessionId,
    artifact_id: p.artifactId,
    input_tokens: p.tokens.input,
    output_tokens: p.tokens.output,
    cache_creation_tokens: p.tokens.cacheWrite,
    cache_read_tokens: p.tokens.cacheRead,
    duration_seconds: p.seconds,
    cost_usd: p.cost,
    unpriced_observation_count: 0,
    started_at: p.startedAt,
    completed_at: p.completedAt,
    model: p.startedAt ? p.phase.model : null,
    requested_model: p.phase.model,
    model_display: p.phase.model,
    cost_by_model: p.startedAt ? { [p.phase.model]: p.cost.toFixed(6) } : {},
    error_message: p.status === 'failed' ? 'Phase exited with a non-zero status' : null,
    failure_classification: p.status === 'failed' ? 'unclassified' : null,
  }
}

export function executionDetail(r: CatalogRun): ExecutionDetailResponse {
  const item = executionListItem(r)
  const phases = phaseDetail(r)
  if (RUNS.indexOf(r) === CANONICAL_RUN) {
    item.total_input_tokens = phases.reduce((n, p) => n + p.input_tokens, 0)
    item.total_output_tokens = phases.reduce((n, p) => n + p.output_tokens, 0)
    item.total_cache_creation_tokens = phases.reduce((n, p) => n + p.cache_creation_tokens, 0)
    item.total_cache_read_tokens = phases.reduce((n, p) => n + p.cache_read_tokens, 0)
  }
  return {
    workflow_execution_id: r.id,
    workflow_id: r.workflowId,
    workflow_name: item.workflow_name,
    status: r.status,
    started_at: r.startedAt,
    completed_at: item.completed_at ?? null,
    phases,
    total_phases: item.total_phases,
    completed_phases: r.done,
    phase_progress: item.phase_progress,
    phase_plan: phases.map((p) => ({ phase_id: p.phase_id, name: p.name, status: p.status, status_display: p.status })),
    total_input_tokens: item.total_input_tokens,
    total_output_tokens: item.total_output_tokens,
    total_cache_creation_tokens: item.total_cache_creation_tokens,
    total_cache_read_tokens: item.total_cache_read_tokens,
    total_tokens: r.tokens,
    total_cost_usd: r.cost,
    unpriced_observation_count: 0,
    artifact_ids: phases.flatMap((p) => (p.artifact_id ? [p.artifact_id] : [])),
    error_message: item.error_message ?? null,
    failure_classification: 'unclassified',
    repos: item.repos ?? [],
    workspace: null,
    task: taskOf(r),
  }
}

/** Session inventory: real reconstruction facts, coverage unproven (board: "1 gap"). */
function inventory(r: CatalogRun): InventoryStatus {
  const sessions = executionDetail(r).phases.filter((p) => p.session_id).length
  const revision = `${fakeId(`rev-${r.id}`, 12)}${fakeId(`rev2-${r.id}`, 24)}`
  return {
    run: { source_instance_id: 'local', execution_id: r.id },
    snapshot: null,
    reconstruction_status: r.status === 'running' ? 'running' : 'current',
    observed_evidence_watermark: sessions * 40,
    later_evidence_pending: r.status === 'running',
    summary: {
      complete: false,
      coverage_state: 'unsupported',
      coverage_display: `The ${sessions === 1 ? 'session' : 'sessions'} above ${sessions === 1 ? 'is' : 'are'} real, but others may exist. Missing host registration affects all ${sessions}.`,
      revision,
      distinct_sessions: sessions,
      platform_sessions: sessions,
      invocations: 0,
      native_transcripts: 0,
      gaps: sessions ? 1 : 0,
      namespaces: null,
      counts_display: `${sessions} platform sessions · 0 native transcripts · 0 invocations · ${sessions ? 1 : 0} gap`,
      remote_replication: 'disabled',
      follow_up_command: `syn executions inventory ${r.id} --refresh`,
    },
  } as InventoryStatus
}

export const executionRoutes: FixtureRoute[] = [
  route('GET', '/executions', ({ query }): ExecutionListResponse => {
    const items = [...RUNS].sort((a, b) => b.startedAt.localeCompare(a.startedAt)).map(executionListItem)
    const textOf = (e: ExecutionListItem) => `${e.workflow_name} ${e.workflow_execution_id} ${e.repos_display ?? ''}`
    const after = fixtureWindowStart(query)
    const inWindow = Number.isNaN(after) ? items : items.filter((e) => e.started_at && Date.parse(e.started_at) >= after)
    const unfiltered = filterList(inWindow, new URLSearchParams({ q: query.get('q') ?? '' }), (e) => e.status, textOf)
    const rows = filterList(inWindow, query, (e) => e.status, textOf)
    const page = paginate(rows, query, 50)
    return {
      executions: page.rows,
      total: page.total,
      page: page.page,
      page_size: page.page_size,
      excluded_undated: 0,
      status_counts: countBy(unfiltered, (e) => e.status),
      budget: { running: 1, queued: 0, limit: 20, admission_paused: false, display: '1 of 20 running' },
    }
  }),
  route('GET', '/executions/:executionId/session-inventory', ({ params }): InventoryStatus => inventory(runOf(params.executionId!) ?? notFound('Execution'))),
  // Fixture inventories have no snapshot (`snapshot: null` above), so pages,
  // node lookups and archived transcripts answer the API's 404.
  route('GET', '/executions/:executionId/session-inventory/:snapshotId/:kind', () => notFound('Inventory snapshot')),
  route('GET', '/executions/:executionId/session-inventory/:snapshotId/nodes/:nodeKey', () => notFound('Inventory snapshot')),
  route('GET', '/executions/:executionId/session-transcripts/:revision', () => notFound('Transcript')),
  route('GET', '/executions/:executionId', ({ params }) => executionDetail(runOf(params.executionId!) ?? notFound('Execution'))),
  route('POST', '/executions/:executionId/cancel', ({ params }) => ({
    success: true,
    execution_id: params.executionId,
    state: 'cancelling',
    message: 'Fixtures mode: nothing was cancelled.',
  })),
]
