import type {
  ExecutionHistoryResponse,
  PhaseDefinition,
  PhaseMetrics,
  WorkflowExecutionSummary,
  WorkflowResponse,
  WorkflowSummary,
} from '../types'
import { type CatalogRun, type CatalogWorkflow, RUNS, WORKFLOWS, phaseRuns, workflowOf } from './catalog'
import { type FixtureRoute, notFound, route } from './define'
import { FIXTURE_NOW, paginate } from './seed'

const runsOf = (workflowId: string) => RUNS.filter((r) => r.workflowId === workflowId)
const createdAt = (w: CatalogWorkflow) => new Date(FIXTURE_NOW - (WORKFLOWS.indexOf(w) + 8) * 7 * 86_400_000).toISOString()

export function workflowSummary(w: CatalogWorkflow): WorkflowSummary {
  return { id: w.id, name: w.name, workflow_type: w.type, phase_count: w.phases.length, created_at: createdAt(w), runs_count: runsOf(w.id).length }
}

function phaseDefinition(w: CatalogWorkflow, index: number): PhaseDefinition {
  const p = w.phases[index]!
  return {
    phase_id: p.id,
    name: p.name,
    order: index + 1,
    description: null,
    agent_type: p.provider,
    prompt_template: `You are the ${p.name} phase of ${w.name}.\n\nTask: {{task}}`,
    timeout_seconds: 1800,
    allowed_tools: ['Read', 'Write', 'Bash', 'Grep'],
    argument_hint: null,
    model: p.model,
    resolved_model: null,
    resolution_basis: null,
    model_display: p.model,
    provider: p.provider,
    skills: [],
  }
}

export function workflowDetail(w: CatalogWorkflow): WorkflowResponse {
  return {
    id: w.id,
    name: w.name,
    description: w.description,
    workflow_type: w.type,
    classification: 'standard',
    phases: w.phases.map((_, i) => phaseDefinition(w, i)),
    input_declarations: [{ name: 'task', description: 'What to do', required: true, default: null }],
    created_at: createdAt(w),
    runs_count: runsOf(w.id).length,
    runs_link: `/workflows/${w.id}/runs`,
  }
}

export function phaseMetrics(r: CatalogRun): PhaseMetrics[] {
  return phaseRuns(r).map((p) => ({
    phase_id: p.phase.id,
    phase_name: p.phase.name,
    status: p.status,
    input_tokens: p.tokens.input,
    output_tokens: p.tokens.output,
    total_tokens: p.tokens.input + p.tokens.output + p.tokens.cacheWrite + p.tokens.cacheRead,
    cost_usd: p.cost.toFixed(6),
    unpriced_observation_count: 0,
    cost_in_progress: p.status === 'running',
    duration_seconds: p.seconds,
    artifact_count: p.artifactId ? 1 : 0,
  }))
}

export function runSummary(r: CatalogRun): WorkflowExecutionSummary {
  const total = workflowOf(r.workflowId)?.phases.length ?? 0
  return {
    workflow_execution_id: r.id,
    workflow_id: r.workflowId,
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
    total_cost_usd: r.cost,
    failure_classification: 'unclassified',
  }
}

export const workflowRoutes: FixtureRoute[] = [
  route('GET', '/workflows', ({ query }) => {
    const search = query.get('search')?.toLowerCase() ?? ''
    const type = query.get('workflow_type')
    const rows = WORKFLOWS.filter((w) => (!search || w.name.toLowerCase().includes(search)) && (!type || w.type === type)).map(workflowSummary)
    const page = paginate(rows, query, 20)
    return { workflows: page.rows, total: page.total, page: page.page, page_size: page.page_size }
  }),
  route('GET', '/workflows/:workflowId', ({ params }) => {
    const w = workflowOf(params.workflowId!) ?? notFound('Workflow')
    return workflowDetail(w)
  }),
  route('GET', '/workflows/:workflowId/runs', ({ params }) => {
    workflowOf(params.workflowId!) ?? notFound('Workflow')
    return { runs: runsOf(params.workflowId!).map(runSummary) }
  }),
  route('GET', '/workflows/:workflowId/history', ({ params }): ExecutionHistoryResponse => {
    const w = workflowOf(params.workflowId!) ?? notFound('Workflow')
    const runs = runsOf(w.id)
    return {
      workflow_id: w.id,
      workflow_name: w.name,
      total_executions: runs.length,
      executions: runs.map((r) => ({
        workflow_execution_id: r.id,
        status: r.status,
        started_at: r.startedAt,
        completed_at: runSummary(r).completed_at,
        total_tokens: r.tokens,
        total_cost_usd: r.cost,
        phase_results: phaseMetrics(r),
        error_message: r.status === 'failed' ? 'Phase exited with a non-zero status' : null,
      })),
    }
  }),
  route('POST', '/workflows/:workflowId/execute', ({ params }) => {
    const w = workflowOf(params.workflowId!) ?? notFound('Workflow')
    return { execution_id: 'fixture-new-run', workflow_id: w.id, status: 'queued', message: 'Fixtures mode: nothing was started.' }
  }),
  route('PUT', '/workflows/:workflowId/phases/:phaseId', ({ params }) => ({
    workflow_id: params.workflowId,
    phase_id: params.phaseId,
    status: 'updated',
  })),
]
