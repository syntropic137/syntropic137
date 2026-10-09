import type { ConversationLogResponse, ToolTimelineResponse, TokenMetricsResponse } from '../resources/observability'
import type { CostSummary, ExecutionCost, MetricsResponse, SessionCost } from '../types'
import { RUNS, phaseRuns, runOf } from './catalog'
import { executionDetail } from './executions'
import { type FixtureRoute, notFound, route } from './define'
import { FIXTURE_NOW } from './seed'
import { allPhaseRuns, sessionDetail } from './sessions'
import { phaseMetrics } from './workflows'

const findSession = (id: string) => allPhaseRuns().find((p) => p.sessionId === id) ?? notFound('Session')

function metrics(): MetricsResponse {
  const sessions = allPhaseRuns()
  const sum = (k: 'input' | 'output' | 'cacheWrite' | 'cacheRead') => sessions.reduce((n, p) => n + p.tokens[k], 0)
  const count = (s: string) => RUNS.filter((r) => r.status === s).length
  const tokens = { input: sum('input'), output: sum('output'), cacheWrite: sum('cacheWrite'), cacheRead: sum('cacheRead') }
  return {
    total_workflows: RUNS.length,
    completed_workflows: count('completed'),
    failed_workflows: count('failed'),
    execution_status_counts: { not_started: 0, running: count('running'), completed: count('completed'), failed: count('failed'), cancelled: count('cancelled'), interrupted: 0 },
    total_sessions: sessions.length,
    total_input_tokens: tokens.input,
    total_output_tokens: tokens.output,
    total_cache_creation_tokens: tokens.cacheWrite,
    total_cache_read_tokens: tokens.cacheRead,
    total_tokens: tokens.input + tokens.output + tokens.cacheWrite + tokens.cacheRead,
    total_cost_usd: RUNS.reduce((n, r) => n + r.cost, 0),
    total_artifacts: sessions.filter((p) => p.artifactId).length,
    total_artifact_bytes: sessions.filter((p) => p.artifactId).length * 20_275,
    phases: RUNS.slice(0, 3).flatMap(phaseMetrics),
  }
}

function sessionCost(id: string): SessionCost {
  const p = findSession(id)
  const d = sessionDetail(p)
  return {
    session_id: d.id,
    execution_id: d.execution_id,
    workflow_id: d.workflow_id,
    phase_id: d.phase_id,
    workspace_id: null,
    total_cost_usd: d.total_cost_usd,
    token_cost_usd: d.total_cost_usd,
    compute_cost_usd: 0,
    input_tokens: d.input_tokens,
    output_tokens: d.output_tokens,
    total_tokens: d.total_tokens,
    cache_creation_tokens: d.cache_creation_tokens,
    cache_read_tokens: d.cache_read_tokens,
    tool_calls: 2,
    turns: 3,
    duration_ms: (d.duration_seconds ?? 0) * 1000,
    cost_by_model: d.cost_by_model,
    cost_by_tool: { Bash: (d.total_cost_usd * 0.6).toFixed(6), Read: (d.total_cost_usd * 0.4).toFixed(6) },
    tokens_by_tool: { Bash: Math.round(d.total_tokens * 0.6), Read: Math.round(d.total_tokens * 0.4) },
    cost_by_tool_tokens: { Bash: (d.total_cost_usd * 0.6).toFixed(6), Read: (d.total_cost_usd * 0.4).toFixed(6) },
    is_finalized: d.status !== 'running',
    unpriced_observation_count: 0,
    started_at: d.started_at,
    completed_at: d.completed_at,
  }
}

function executionCost(id: string): ExecutionCost {
  const r = runOf(id) ?? notFound('Execution')
  const d = executionDetail(r)
  const phases = phaseRuns(r).filter((p) => p.sessionId)
  return {
    execution_id: r.id,
    workflow_id: r.workflowId,
    session_count: phases.length,
    session_ids: phases.map((p) => p.sessionId!),
    total_cost_usd: r.cost,
    token_cost_usd: r.cost,
    compute_cost_usd: 0,
    input_tokens: d.total_input_tokens,
    output_tokens: d.total_output_tokens,
    total_tokens: d.total_tokens,
    cache_creation_tokens: d.total_cache_creation_tokens,
    cache_read_tokens: d.total_cache_read_tokens,
    tool_calls: phases.length * 2,
    turns: phases.length * 3,
    duration_ms: r.seconds * 1000,
    cost_by_phase: Object.fromEntries(phases.map((p) => [p.phase.id, p.cost.toFixed(6)])),
    unpriced_by_phase: {},
    cost_by_model: Object.fromEntries(phases.map((p) => [p.phase.model, p.cost.toFixed(6)])),
    cost_by_tool: {},
    is_complete: r.status !== 'running',
    unpriced_observation_count: 0,
    started_at: r.startedAt,
    completed_at: d.completed_at,
  }
}

export const observabilityRoutes: FixtureRoute[] = [
  route('GET', '/metrics', () => metrics()),
  route('GET', '/costs/summary', (): CostSummary => {
    const m = metrics()
    return {
      total_cost_usd: m.total_cost_usd,
      total_sessions: m.total_sessions,
      total_executions: RUNS.length,
      total_tokens: m.total_tokens,
      total_tool_calls: m.total_sessions * 2,
      top_models: [
        { model: 'claude-sonnet-4-5', cost_usd: '2.410000' },
        { model: 'gpt-5-codex', cost_usd: '0.880000' },
      ],
      top_sessions: allPhaseRuns()
        .slice(0, 5)
        .map((p) => ({ session_id: p.sessionId!, cost_usd: p.cost.toFixed(6), tokens: p.tokens.input + p.tokens.output })),
    }
  }),
  route('GET', '/costs/sessions', ({ query }) => {
    const exec = query.get('execution_id')
    return allPhaseRuns()
      .filter((p) => !exec || p.run.id === exec)
      .map((p) => sessionCost(p.sessionId!))
  }),
  route('GET', '/costs/sessions/:sessionId', ({ params }) => sessionCost(params.sessionId!)),
  route('GET', '/costs/executions', () => RUNS.map((r) => executionCost(r.id))),
  route('GET', '/costs/executions/:executionId', ({ params }) => executionCost(params.executionId!)),
  route('GET', '/observability/sessions/:sessionId/tools', ({ params }): ToolTimelineResponse => {
    const d = sessionDetail(findSession(params.sessionId!))
    const tools = d.operations.filter((o) => o.tool_name)
    return {
      session_id: d.id,
      executions: tools.map((o, i) => ({
        event_id: `${o.operation_id}-evt`,
        session_id: d.id,
        tool_name: o.tool_name!,
        tool_use_id: o.tool_use_id ?? `toolu_${i}`,
        status: 'completed',
        started_at: o.timestamp ?? new Date(FIXTURE_NOW).toISOString(),
        duration_ms: (o.duration_seconds ?? 0) * 1000,
        success: o.success,
        tool_input: o.tool_input ?? {},
        tool_output: o.tool_output ?? undefined,
      })),
      total_executions: tools.length,
      completed_count: tools.length,
      blocked_count: 0,
      success_rate: tools.length ? tools.filter((o) => o.success).length / tools.length : null,
    }
  }),
  route('GET', '/observability/sessions/:sessionId/tokens', ({ params }): TokenMetricsResponse => {
    const d = sessionDetail(findSession(params.sessionId!))
    return { session_id: d.id, total_input_tokens: d.input_tokens, total_output_tokens: d.output_tokens, total_tokens: d.total_tokens, message_count: 3 }
  }),
  route('GET', '/conversations/:sessionId', ({ params }): ConversationLogResponse => {
    const d = sessionDetail(findSession(params.sessionId!))
    const raw = [
      JSON.stringify({ type: 'system', subtype: 'init', cwd: '/workspace', session_id: d.id }),
      JSON.stringify({ type: 'assistant', message: { content: [{ type: 'text', text: 'Starting.' }] } }),
    ]
    return {
      session_id: d.id,
      lines: raw.map((line, i) => ({
        line_number: i + 1,
        raw: line,
        parsed: JSON.parse(line) as Record<string, unknown>,
        event_type: i === 0 ? 'system' : 'assistant',
        tool_name: null,
        content_preview: i === 0 ? 'init' : 'Starting.',
      })),
      total_lines: raw.length,
      metadata: null,
    }
  }),
  route('GET', '/sse/health', () => ({ status: 'ok', active_executions: 1, active_connections: 0 })),
  route('GET', '/features', () => ({ ui_feedback: true })),
  // Shaped like a real beta deploy: PEP 440 version, semver image tag, a full sha, live 2h13m before FIXTURE_NOW.
  route('GET', '/version', () => ({
    version: '0.33.2b23',
    image_tag: 'v0.33.2-beta.23',
    commit: '4f2a9c81d03e6b57a1c9e0f4b8d27365ce1a90b4',
    started_at: new Date(FIXTURE_NOW - (2 * 60 + 13) * 60_000).toISOString(),
    version_status: 'installed',
    started_at_display: '2026-10-08 06:47 UTC',
  })),
]
