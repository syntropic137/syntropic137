import type { ExecutionDetailResponse, ExecutionListResponse, PhaseExecutionDetail } from '../types'
import { type CatalogRun, RUNS, phaseRuns, runOf, workflowOf } from './catalog'
import { type FixtureRoute, notFound, route } from './define'
import { costDisplay, countBy, durationDisplay, filterList, paginate, tokensDisplay } from './seed'

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
  return phaseRuns(r).map((p) => ({
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
  }))
}

export function executionDetail(r: CatalogRun): ExecutionDetailResponse {
  const item = executionListItem(r)
  const phases = phaseDetail(r)
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
    task: 'Survey how agent harnesses record token usage and summarise the differences.',
  }
}

export const executionRoutes: FixtureRoute[] = [
  route('GET', '/executions', ({ query }): ExecutionListResponse => {
    const items = RUNS.map(executionListItem)
    const textOf = (e: ExecutionListItem) => `${e.workflow_name} ${e.workflow_execution_id} ${e.repos_display ?? ''}`
    const unfiltered = filterList(items, new URLSearchParams({ q: query.get('q') ?? '' }), (e) => e.status, textOf)
    const rows = filterList(items, query, (e) => e.status, textOf)
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
  route('GET', '/executions/:executionId', ({ params }) => executionDetail(runOf(params.executionId!) ?? notFound('Execution'))),
  route('POST', '/executions/:executionId/cancel', ({ params }) => ({
    success: true,
    execution_id: params.executionId,
    state: 'cancelling',
    message: 'Fixtures mode: nothing was cancelled.',
  })),
]
