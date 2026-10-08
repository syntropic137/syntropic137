import type { SessionListItem, SessionListResponse } from '../resources/sessions'
import type { OperationInfo, SessionResponse } from '../types'
import { type CatalogPhaseRun, RUNS, phaseRuns, workflowOf } from './catalog'
import { type FixtureRoute, notFound, route } from './define'
import { after, costDisplay, countBy, durationDisplay, filterList, paginate, tokensDisplay } from './seed'

export function allPhaseRuns(): CatalogPhaseRun[] {
  return RUNS.flatMap(phaseRuns).filter((p) => p.sessionId !== null)
}

const total = (p: CatalogPhaseRun) => p.tokens.input + p.tokens.output + p.tokens.cacheWrite + p.tokens.cacheRead

export function sessionListItem(p: CatalogPhaseRun): SessionListItem {
  const w = workflowOf(p.run.workflowId)
  return {
    id: p.sessionId!,
    workflow_id: p.run.workflowId,
    workflow_name: w?.name ?? null,
    execution_id: p.run.id,
    phase_id: p.phase.id,
    phase_display: p.phase.name,
    status: p.status,
    agent_provider: p.phase.provider,
    agent_model: p.phase.model,
    requested_model: p.phase.model,
    agent_model_display: p.phase.model,
    repos: p.run.repo ? [p.run.repo] : [],
    repos_display: p.run.repo ? p.run.repo.replace('https://github.com/', '') : null,
    input_tokens: p.tokens.input,
    output_tokens: p.tokens.output,
    cache_creation_tokens: p.tokens.cacheWrite,
    cache_read_tokens: p.tokens.cacheRead,
    total_tokens: total(p),
    total_tokens_display: tokensDisplay(total(p)),
    total_cost_usd: p.cost.toFixed(6),
    total_cost_display: costDisplay(p.cost),
    unpriced_observation_count: 0,
    duration_seconds: p.seconds,
    duration_display: durationDisplay(p.seconds),
    started_at: p.startedAt,
    completed_at: p.completedAt,
  }
}

function operations(p: CatalogPhaseRun): OperationInfo[] {
  const t0 = p.startedAt ?? new Date(0).toISOString()
  return [
    { operation_id: `${p.sessionId}-1`, operation_type: 'message', timestamp: t0, success: true, message_role: 'user', message_content: `Run the ${p.phase.name} phase.` },
    {
      operation_id: `${p.sessionId}-2`,
      operation_type: 'tool_execution',
      timestamp: after(t0, 4_000),
      duration_seconds: 1.2,
      success: true,
      tool_name: 'Bash',
      tool_use_id: 'toolu_01',
      tool_input: { command: 'ls -la /workspace' },
      tool_output: 'total 8\ndrwxr-xr-x  4 agent agent 128 .\n-rw-r--r--  1 agent agent  42 README.md',
    },
    {
      operation_id: `${p.sessionId}-3`,
      operation_type: 'tool_execution',
      timestamp: after(t0, 9_000),
      duration_seconds: 0.4,
      success: p.status !== 'failed',
      tool_name: 'Read',
      tool_use_id: 'toolu_02',
      tool_input: { file_path: '/workspace/README.md' },
      tool_output: p.status === 'failed' ? null : '# Workspace',
      error_message: p.status === 'failed' ? 'File not found' : null,
    },
  ]
}

export function sessionDetail(p: CatalogPhaseRun): SessionResponse {
  const item = sessionListItem(p)
  return {
    id: item.id,
    workflow_id: item.workflow_id,
    workflow_name: item.workflow_name ?? null,
    execution_id: p.run.id,
    phase_id: p.phase.id,
    phase_display: p.phase.name,
    milestone_id: null,
    agent_provider: p.phase.provider,
    agent_model: p.phase.model,
    requested_model: p.phase.model,
    agent_model_display: p.phase.model,
    status: p.status,
    input_tokens: p.tokens.input,
    output_tokens: p.tokens.output,
    cache_creation_tokens: p.tokens.cacheWrite,
    cache_read_tokens: p.tokens.cacheRead,
    total_tokens: total(p),
    total_cost_usd: p.cost,
    unpriced_observation_count: 0,
    cost_by_model: { [p.phase.model]: p.cost.toFixed(6) },
    operations: operations(p),
    started_at: p.startedAt,
    completed_at: p.completedAt,
    duration_seconds: p.seconds,
    error_message: p.status === 'failed' ? 'Phase exited with a non-zero status' : null,
    metadata: {},
  }
}

export const sessionRoutes: FixtureRoute[] = [
  route('GET', '/sessions', ({ query }): SessionListResponse => {
    const items = allPhaseRuns().map(sessionListItem)
    const workflowId = query.get('workflow_id')
    const scoped = workflowId ? items.filter((s) => s.workflow_id === workflowId) : items
    const textOf = (s: SessionListItem) => `${s.id} ${s.workflow_name ?? ''} ${s.phase_display ?? ''}`
    const rows = filterList(scoped, query, (s) => s.status, textOf)
    const page = paginate(rows, query, 50)
    return {
      sessions: page.rows,
      total: page.total,
      page: page.page,
      page_size: page.page_size,
      excluded_undated: 0,
      status_counts: countBy(filterList(scoped, new URLSearchParams({ q: query.get('q') ?? '' }), (s) => s.status, textOf), (s) => s.status),
    }
  }),
  route('GET', '/sessions/:sessionId', ({ params }) => {
    const p = allPhaseRuns().find((x) => x.sessionId === params.sessionId) ?? notFound('Session')
    return sessionDetail(p)
  }),
]
