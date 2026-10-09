/**
 * Workflow detail and runs (Workflow, PhoneWorkflow boards): the header
 * figures, the agent prompt spec, each phase's latest output, and the
 * filtered, paged run list for one workflow. Structural inputs only: the API
 * types satisfy them, and nothing here imports the data package.
 */
import { formatBytes } from '../../format/bytes'
import { formatCostPrecise } from '../../format/cost'
import { toNumber, toTime } from '../../format/shared'
import { formatTokens } from '../../format/tokens'
import type { Figure } from '../../patterns/headers'
import type { AgentPromptSpec } from '../../patterns/agentPrompt'
import { statusKind, type StatusKind } from '../../patterns/status'
import { type TimeWindow, timeWindowStart } from '../executions/list'

// ---------------------------------------------------------------- header

export interface WorkflowRunLike {
  workflow_execution_id: string
  status: string
  started_at: string | null
  completed_at?: string | null
  completed_phases?: number
  total_phases?: number
  total_tokens?: number | null
  total_cost_usd?: number | string | null
}

export interface WorkflowTotals {
  runs: number
  tokens: number
  cost: number
}

export function workflowTotals(runsCount: number, runs: readonly WorkflowRunLike[] | null): WorkflowTotals {
  const list = runs ?? []
  return {
    runs: Math.max(runsCount, list.length),
    tokens: list.reduce((a, r) => a + (r.total_tokens ?? 0), 0),
    cost: list.reduce((a, r) => a + (toNumber(r.total_cost_usd ?? null) ?? 0), 0),
  }
}

/** Header figures: Runs, Phases, Tokens, Spend. Tokens and spend wait for the run list. */
export function workflowFigures(phaseCount: number, runsCount: number, runs: readonly WorkflowRunLike[] | null): Figure[] {
  const t = workflowTotals(runsCount, runs)
  return [
    { label: 'Runs', value: String(t.runs) },
    { label: 'Phases', value: String(phaseCount) },
    { label: 'Tokens', value: runs ? formatTokens(t.tokens, { case: 'upper' }) : '—' },
    { label: 'Spend', value: runs ? formatCostPrecise(t.cost) : '—' },
  ]
}

export interface InputDeclarationLike {
  name: string
  description?: string | null
  required: boolean
  default?: string | null
}

/** "Copy for an agent": the CLI command, the inputs and the phases in order. */
export function workflowPromptSpec(w: { id: string; name: string; phases: readonly { name: string }[]; input_declarations?: readonly InputDeclarationLike[] | null }): AgentPromptSpec {
  const decls = w.input_declarations ?? []
  const hasTask = decls.some((d) => d.name === 'task')
  const inputs = decls.map((d) => ({
    name: d.name,
    required: d.required,
    ...(d.description ? { description: d.name === 'task' ? `${d.description}. Fills $ARGUMENTS in the phase prompts.` : d.description } : {}),
    placeholder: d.name === 'task' ? '<what to do>' : `<${d.name}>`,
  }))
  return {
    workflowName: w.name,
    workflowId: w.id,
    inputs: hasTask ? inputs : [{ name: 'task', required: false, description: 'Fills $ARGUMENTS in the phase prompts.', placeholder: '<what to do>' }, ...inputs],
    phases: w.phases.map((p) => p.name),
  }
}

/** Tags under the title: type, classification, and whether runs get repositories. */
export function workflowTags(w: { workflow_type: string; classification?: string | null; requires_repos?: boolean | null; tags?: readonly string[] | null }): string[] {
  const out = [w.workflow_type || 'custom']
  if (w.classification) out.push(w.classification)
  if (w.requires_repos === true) out.push('needs repos')
  else if (w.requires_repos === false) out.push('no repos')
  for (const t of w.tags ?? []) if (!out.includes(t)) out.push(t)
  return out
}

/** Whether a task typed at kickoff reaches any phase ($ARGUMENTS or {{task}}). */
export function consumesTask(phases: readonly { prompt_template?: string | null }[]): boolean {
  return phases.some((p) => /\$ARGUMENTS|\{\{\s*task\s*\}\}/.test(p.prompt_template ?? ''))
}

/** Run form: every required input (task aside) has a value, and a required task is given. */
export function canStartRun(decls: readonly InputDeclarationLike[], task: string, inputs: Readonly<Record<string, string>>): boolean {
  for (const d of decls) {
    if (!d.required) continue
    const v = d.name === 'task' ? task : (inputs[d.name] ?? '')
    if (!v.trim() && !d.default) return false
  }
  return true
}

// ---------------------------------------------------------------- latest output

export interface ArtifactLike {
  id: string
  title?: string | null
  artifact_type: string
  size_bytes: number
  execution_id?: string | null
}

export interface LatestOutput {
  artifactId: string
  title: string
  meta: string
  executionId: string | null
}

/** One phase's latest output as the board's "Latest output" row: "deliverable.md", "2.9 KB · exec-66e14f23". */
export function latestOutputOf(a: ArtifactLike | null | undefined): LatestOutput | null {
  if (!a) return null
  const exec = a.execution_id ?? null
  return {
    artifactId: a.id,
    title: a.title || a.artifact_type,
    meta: [formatBytes(a.size_bytes), exec ? exec.slice(0, 13) : null].filter(Boolean).join(' · '),
    executionId: exec,
  }
}

export function latestOutputsByPhase(phases: readonly { phase_id: string; artifact?: ArtifactLike | null }[]): Record<string, LatestOutput | null> {
  const out: Record<string, LatestOutput | null> = {}
  for (const p of phases) out[p.phase_id] = latestOutputOf(p.artifact)
  return out
}

// ---------------------------------------------------------------- runs list

/** Status chips on the Runs page, in board order. */
export const RUN_FILTERS: readonly { value: RunFilter; label: string }[] = [
  { value: 'all', label: 'All' },
  { value: 'running', label: 'Running' },
  { value: 'completed', label: 'Completed' },
  { value: 'failed', label: 'Failed' },
  { value: 'cancelled', label: 'Cancelled' },
]

export type RunFilter = 'all' | 'running' | 'completed' | 'failed' | 'cancelled'

export function parseRunFilter(v: string | null | undefined): RunFilter {
  return RUN_FILTERS.some((f) => f.value === v) ? (v as RunFilter) : 'all'
}

/** The chip a run counts under: pending and queued count as running, interrupted as cancelled. */
export function runFilterOf(status: string): Exclude<RunFilter, 'all'> | null {
  const k: StatusKind = statusKind(status)
  if (k === 'running' || k === 'pending') return 'running'
  if (k === 'interrupted') return 'cancelled'
  return k === 'completed' || k === 'failed' || k === 'cancelled' ? k : null
}

export interface RunsView<T> {
  rows: T[]
  /** Runs in the window, before the status filter. */
  inWindow: number
  /** Runs matching window and status. */
  matched: number
  counts: Record<RunFilter, number>
  page: number
  pageCount: number
  /** Longest duration on the page, ms (the Run Row bar scale). */
  longestMs: number
}

/** Run duration in ms: finished runs to completion, running ones to `now`; null if undated. */
export function runDurationMs(r: Pick<WorkflowRunLike, 'started_at' | 'completed_at'>, now: number): number | null {
  const s = toTime(r.started_at)
  if (s === null) return null
  const e = r.completed_at ? toTime(r.completed_at) : now
  return e === null ? null : Math.max(0, e - s)
}

/** Window, status and page over a workflow's full run list (the API returns it all, newest first). */
export function runsView<T extends WorkflowRunLike>(runs: readonly T[], opts: { status: RunFilter; window: TimeWindow; page: number; pageSize: number; now: number }): RunsView<T> {
  const since = timeWindowStart(opts.window, opts.now)
  const sinceT = since ? Date.parse(since) : null
  const windowed = runs
    .filter((r) => sinceT === null || (toTime(r.started_at) ?? -Infinity) >= sinceT)
    .sort((a, b) => (toTime(b.started_at) ?? 0) - (toTime(a.started_at) ?? 0))
  const counts: Record<RunFilter, number> = { all: windowed.length, running: 0, completed: 0, failed: 0, cancelled: 0 }
  for (const r of windowed) {
    const f = runFilterOf(r.status)
    if (f) counts[f]++
  }
  const matched = opts.status === 'all' ? windowed : windowed.filter((r) => runFilterOf(r.status) === opts.status)
  const pageCount = Math.max(1, Math.ceil(matched.length / opts.pageSize))
  const page = Math.min(Math.max(1, opts.page), pageCount)
  const rows = matched.slice((page - 1) * opts.pageSize, page * opts.pageSize)
  const longestMs = Math.max(0, ...rows.map((r) => runDurationMs(r, opts.now) ?? 0))
  return { rows, inWindow: windowed.length, matched: matched.length, counts, page, pageCount, longestMs }
}

/** "Showing 1-50 of 305 runs" / "No runs in this window". */
export function runsSummary(view: Pick<RunsView<unknown>, 'page' | 'matched' | 'rows'>, pageSize: number, status: RunFilter): string {
  if (view.matched === 0) return 'No runs'
  const from = (view.page - 1) * pageSize + 1
  const what = status === 'all' ? 'runs' : `${status} runs`
  return `Showing ${from}-${from + view.rows.length - 1} of ${view.matched} ${what}`
}
