/**
 * One coherent, populated API world for screenshotting the dashboard (#1647).
 *
 * `scripts/screenshot.mjs --fixtures fixtures/screenshot.json` answers every
 * `/api/` request from that file, keyed by pathname. This module is the source
 * of the file: `pnpm fixtures:screenshot` writes it, and
 * `screenshotFixtures.test.ts` fails when the committed JSON has drifted.
 *
 * Every body is typed by its route, through `fixture()`: the route is a key of
 * the generated `paths`, and the body must be that route's 200 response. So a
 * body that stops matching the API, or a route the API no longer serves, fails
 * `tsc -b`. The test re-checks the routes against the OpenAPI spec at runtime.
 *
 * Display fields hold what the API renders for the raw values beside them
 * (`format_cost`, `format_tokens`, `format_duration_seconds` and
 * `format_observed_model` in syn_shared.display / syn_shared.observed_model).
 * The client never formats them, so a wrong one here would show a wrong page.
 *
 * Limits, inherited from screenshot.mjs: the query string is ignored, so a
 * list route returns the same rows for every filter and page; SSE routes and
 * `/artifacts/{id}/raw` are not JSON and are left unanswered (404).
 */

import { API_BASE } from '../api/base'
import type { components, paths } from '../generated/api-types'

type Schemas = components['schemas']

/** A route whose GET answers 200 with a JSON body. */
type JsonGetRoute = {
  [P in keyof paths]: paths[P] extends {
    get: { responses: { 200: { content: { 'application/json': unknown } } } }
  }
    ? P
    : never
}[keyof paths]

type BodyOf<P extends JsonGetRoute> = paths[P]['get']['responses'][200]['content']['application/json']

type PathParamsOf<P extends JsonGetRoute> = paths[P]['get']['parameters'] extends {
  path: infer A extends Readonly<Record<string, string>>
}
  ? A
  : Readonly<Record<string, never>>

/** One answered request: the spec route it belongs to, the pathname the browser asks for, the body. */
export interface ScreenshotFixture {
  readonly route: JsonGetRoute
  readonly pathname: string
  readonly body: unknown
}

function fixture<P extends JsonGetRoute>(route: P, params: PathParamsOf<P>, body: BodyOf<P>): ScreenshotFixture {
  const values: Readonly<Record<string, string>> = params
  const filled = route.replace(/\{(\w+)\}/g, (_, name: string) => {
    const value = values[name]
    if (value === undefined) throw new Error(`fixture for ${route}: no value for {${name}}`)
    return encodeURIComponent(value)
  })
  return { route, pathname: `${API_BASE}${filled}`, body }
}

// ---------------------------------------------------------------------------
// Ids. Everything below refers to these, so the pages link to each other.
// ---------------------------------------------------------------------------

export const WORKFLOW_ID = 'wf-sdlc-implement'
const WORKFLOW_NAME = 'SDLC implement'
export const COMPLETED_EXECUTION_ID = 'exec-0c5d1e7a'
export const FAILED_EXECUTION_ID = 'exec-1f9b2c40'
export const RUNNING_EXECUTION_ID = 'exec-2a7e4d93'
export const PLAN_SESSION_ID = 'sess-plan-0c5d'
const IMPLEMENT_SESSION_ID = 'sess-impl-0c5d'
const REVIEW_SESSION_ID = 'sess-review-0c5d'
const FAILED_SESSION_ID = 'sess-impl-1f9b'
const RUNNING_SESSION_ID = 'sess-plan-2a7e'
export const MARKDOWN_ARTIFACT_ID = 'art-plan-md'
export const PNG_ARTIFACT_ID = 'art-dashboard-png'
const REPO = 'syntropic137/syntropic137'

const OPUS = 'claude-opus-5-5'
const SONNET = 'claude-sonnet-5-5'
const CODEX = 'gpt-5.5-codex'

const PHASES = [
  { phase_id: 'plan', name: 'Plan' },
  { phase_id: 'implement', name: 'Implement' },
  { phase_id: 'review', name: 'Review' },
] as const

// ---------------------------------------------------------------------------
// Health, version, features: the app shell asks for these on every page.
// ---------------------------------------------------------------------------

const BUILD: Schemas['BuildInfo'] = {
  version: '1.0.6',
  version_status: 'installed',
  image_tag: 'v1.0.6',
  commit: 'e7e7a2ee5',
  started_at: '2026-11-26T08:00:00Z',
  started_at_display: '2026-11-26 08:00 UTC',
}

const HEALTH: Schemas['HealthResponse'] = {
  status: 'healthy',
  mode: 'full',
  build: BUILD,
  subscription: { status: 'healthy', running: true, held_projections: [], rebuilding_read_models: [] },
}

// ---------------------------------------------------------------------------
// Executions: one completed (two priced models and one unpriced), one failed,
// one running.
// ---------------------------------------------------------------------------

type Phase = Schemas['PhaseExecutionInfo']

/**
 * Every phase here has `start_pins_status: 'unavailable'` and no pins, so
 * `summarize_skill_use(None, ...)` (routes/executions/phase_skill_use.py)
 * answers `unavailable`: a non-use nobody measured is not reported as one.
 */
const SKILLS_UNAVAILABLE: Schemas['PhaseSkillUseInfo'] = {
  status: 'unavailable',
  declared: [],
  invoked: [],
  provider: null,
  declared_not_invoked: [],
  status_display: 'unavailable: no record for this run',
  summary_display: 'skill use unavailable: no record for this run',
}

function phase(overrides: Partial<Phase> & Pick<Phase, 'phase_id' | 'name' | 'status'>): Phase {
  return {
    input_tokens: 0,
    output_tokens: 0,
    cache_creation_tokens: 0,
    cache_read_tokens: 0,
    total_tokens: 0,
    cost_usd: '0',
    unpriced_observation_count: 0,
    cost_display: '$0.00',
    deliverable_recovered: false,
    start_pins_status: 'unavailable',
    unpriced_model_cost_display: 'unpriced',
    cost_by_model: {},
    cost_by_model_display: {},
    requested_model: null,
    model_display: 'unknown',
    skill_use: SKILLS_UNAVAILABLE,
    ...overrides,
  }
}

const COMPLETED_PHASES: Phase[] = [
  phase({
    ...PHASES[0],
    status: 'completed',
    session_id: PLAN_SESSION_ID,
    artifact_id: MARKDOWN_ARTIFACT_ID,
    input_tokens: 48210,
    output_tokens: 6120,
    cache_creation_tokens: 21400,
    cache_read_tokens: 310500,
    total_tokens: 386230,
    duration_seconds: 254,
    cost_usd: '1.84',
    cost_display: '$1.84',
    cost_by_model: { [OPUS]: '1.84' },
    cost_by_model_display: { [OPUS]: '$1.84' },
    started_at: '2026-11-26T09:00:00Z',
    completed_at: '2026-11-26T09:04:14Z',
    agent_provider: 'claude',
    requested_model: OPUS,
    model: OPUS,
    model_display: OPUS,
    reported_side_effects: 'none',
  }),
  phase({
    ...PHASES[1],
    status: 'completed',
    session_id: IMPLEMENT_SESSION_ID,
    artifact_id: PNG_ARTIFACT_ID,
    input_tokens: 102300,
    output_tokens: 18950,
    cache_creation_tokens: 40200,
    cache_read_tokens: 812000,
    total_tokens: 973450,
    duration_seconds: 1312,
    cost_usd: '0.42',
    cost_display: '$0.42',
    cost_by_model: { [SONNET]: '0.42' },
    cost_by_model_display: { [SONNET]: '$0.42' },
    started_at: '2026-11-26T09:04:20Z',
    completed_at: '2026-11-26T09:26:12Z',
    agent_provider: 'claude',
    requested_model: SONNET,
    model: SONNET,
    model_display: SONNET,
    reported_side_effects: 'succeeded',
  }),
  phase({
    ...PHASES[2],
    status: 'completed',
    session_id: REVIEW_SESSION_ID,
    input_tokens: 61000,
    output_tokens: 4300,
    total_tokens: 65300,
    duration_seconds: 406,
    // A codex model with no rate in the price table: tokens, but no dollars.
    cost_usd: '0',
    unpriced_observation_count: 4,
    cost_display: 'unpriced',
    unpriced_models: [CODEX],
    started_at: '2026-11-26T09:26:20Z',
    completed_at: '2026-11-26T09:33:06Z',
    agent_provider: 'codex',
    requested_model: CODEX,
    model: CODEX,
    model_display: CODEX,
    reported_side_effects: 'none',
  }),
]

const FAILED_PHASES: Phase[] = [
  phase({
    ...PHASES[0],
    status: 'completed',
    session_id: 'sess-plan-1f9b',
    input_tokens: 30100,
    output_tokens: 3900,
    total_tokens: 34000,
    duration_seconds: 188,
    cost_usd: '0.97',
    cost_display: '$0.97',
    cost_by_model: { [OPUS]: '0.97' },
    cost_by_model_display: { [OPUS]: '$0.97' },
    started_at: '2026-11-26T07:10:00Z',
    completed_at: '2026-11-26T07:13:08Z',
    agent_provider: 'claude',
    requested_model: OPUS,
    model: OPUS,
    model_display: OPUS,
  }),
  phase({
    ...PHASES[1],
    status: 'failed',
    session_id: FAILED_SESSION_ID,
    input_tokens: 12800,
    output_tokens: 1400,
    total_tokens: 14200,
    duration_seconds: 95,
    cost_usd: '0.11',
    cost_display: '$0.11',
    cost_by_model: { [SONNET]: '0.11' },
    cost_by_model_display: { [SONNET]: '$0.11' },
    started_at: '2026-11-26T07:13:10Z',
    completed_at: '2026-11-26T07:14:45Z',
    error_message: 'just preflight-agent failed: 2 fitness checks red',
    failure_classification: 'gate',
    reported_failure_reason: 'task',
    exit_code: 1,
    agent_provider: 'claude',
    requested_model: SONNET,
    model: SONNET,
    model_display: SONNET,
  }),
]

const RUNNING_PHASES: Phase[] = [
  phase({
    ...PHASES[0],
    status: 'running',
    session_id: RUNNING_SESSION_ID,
    input_tokens: 9100,
    output_tokens: 800,
    total_tokens: 9900,
    // Mid-run: the cost so far is known, its per-model split is not yet.
    cost_usd: '0.21',
    cost_display: '$0.21',
    started_at: '2026-11-26T10:00:00Z',
    agent_provider: 'claude',
    requested_model: OPUS,
    model_display: `${OPUS} (requested)`,
  }),
]

type Detail = Schemas['ExecutionDetailResponse']

/**
 * Cache multipliers of the price table (`cache_rate_multipliers` in
 * syn_shared.pricing) for the models this world runs. The codex model has no
 * rate, so it is absent, and a scope that ran it gets no label.
 */
const CACHE_RATES: Readonly<Record<string, { read: string; write: string }>> = {
  [OPUS]: { read: '0.05x rate', write: '1.25x rate' },
  [SONNET]: { read: '0.05x rate', write: '1.25x rate' },
}

/** `cache_rate_display` (syn_api/cache_rate_display.py): a label only when every model agrees on it. */
function cacheRatesOf(models: ReadonlySet<string>): Pick<Detail, 'cache_read_rate_display' | 'cache_write_rate_display'> {
  const rates = [...models].map((m) => CACHE_RATES[m])
  const one = (pick: (r: { read: string; write: string }) => string): string | null => {
    if (rates.length === 0 || rates.some((r) => r === undefined)) return null
    const labels = new Set(rates.map((r) => (r === undefined ? '' : pick(r))))
    return labels.size === 1 ? [...labels][0] : null
  }
  return { cache_read_rate_display: one((r) => r.read), cache_write_rate_display: one((r) => r.write) }
}

/** `_models_run` (routes/executions/queries.py): priced-as models, else the reported model. */
function modelsRun(phases: readonly Phase[]): Set<string> {
  const models = new Set<string>()
  for (const p of phases) {
    const priced = Object.keys(p.cost_by_model ?? {})
    if (priced.length > 0) priced.forEach((m) => models.add(m))
    else if (p.model) models.add(p.model)
  }
  return models
}

/** `unattributed_cost_display` of `model_breakdown_text` (syn_api/cost_by_model_display.py), in cents. */
function unattributedOf(costByModel: Readonly<Record<string, string>>, totalUsd: string): string | null {
  const cents = (usd: string) => Math.round(Number(usd) * 100)
  const attributed = Object.values(costByModel).reduce((n, c) => n + Math.max(cents(c), 0), 0)
  const remainder = Math.max(cents(totalUsd), attributed) - attributed
  return remainder > 0 ? `$${(remainder / 100).toFixed(2)}` : null
}

/** `plan_phases` and `PlannedPhase.status_display` (read_models/phase_plan.py), with nothing skipped or inherited. */
function planOf(phases: readonly Phase[]): Schemas['PlannedPhaseInfo'][] {
  return PHASES.map(({ phase_id, name }) => {
    const ran = phases.find((p) => p.phase_id === phase_id)
    if (!ran) return { phase_id, name, status: 'pending', status_display: 'Pending' }
    const words = ran.status.replace('_', ' ')
    return { phase_id, name, status: ran.status, status_display: words.charAt(0).toUpperCase() + words.slice(1) }
  })
}

/** `PhaseProgress` (read_models/phase_progress.py) for a run with no skipped phases. */
function progressOf(status: string, phases: readonly Phase[]): Schemas['PhaseProgressInfo'] {
  const completed = phases.filter((p) => p.status === 'completed').length
  const possible = PHASES.length
  const ended = ['completed', 'failed', 'cancelled', 'interrupted'].includes(status)
  const display =
    status === 'completed'
      ? `${completed} of ${possible}`
      : ended
        ? `${completed} of up to ${possible}, ${status}`
        : status === 'running'
          ? `phase ${Math.min(completed + 1, possible)} of up to ${possible}`
          : completed === 0
            ? 'not started'
            : `${completed} of up to ${possible}`
  return {
    completed,
    skipped: 0,
    possible,
    remaining_possible: ended ? 0 : possible - completed,
    percent: status === 'completed' ? 100 : Math.round((completed * 100) / possible),
    display,
  }
}

function sumTokens(phases: readonly Phase[]) {
  const sum = (key: 'input_tokens' | 'output_tokens' | 'cache_creation_tokens' | 'cache_read_tokens' | 'total_tokens') =>
    phases.reduce((n, p) => n + p[key], 0)
  return {
    total_input_tokens: sum('input_tokens'),
    total_output_tokens: sum('output_tokens'),
    total_cache_creation_tokens: sum('cache_creation_tokens'),
    total_cache_read_tokens: sum('cache_read_tokens'),
    total_tokens: sum('total_tokens'),
  }
}

/** `ExecutionSkillUseSummary.of` over phases whose skill use is all unavailable. */
const SKILL_USE: Schemas['ExecutionSkillUseSummary'] = {
  declared: [],
  invoked: [],
  never_invoked: [],
  not_known: [],
  summary_display: 'unavailable: no record for this run',
}

const COMPLETED_DETAIL: Detail = {
  workflow_execution_id: COMPLETED_EXECUTION_ID,
  workflow_id: WORKFLOW_ID,
  workflow_name: WORKFLOW_NAME,
  status: 'completed',
  started_at: '2026-11-26T09:00:00Z',
  completed_at: '2026-11-26T09:33:06Z',
  phases: COMPLETED_PHASES,
  total_phases: 3,
  completed_phases: 3,
  phase_progress: progressOf('completed', COMPLETED_PHASES),
  phase_plan: planOf(COMPLETED_PHASES),
  ...cacheRatesOf(modelsRun(COMPLETED_PHASES)),
  ...sumTokens(COMPLETED_PHASES),
  total_cost_usd: '2.26',
  unpriced_observation_count: 4,
  total_cost_display: '>=$2.26 (partial)',
  cost_by_model: { [OPUS]: '1.84', [SONNET]: '0.42' },
  cost_by_model_display: { [OPUS]: '$1.84', [SONNET]: '$0.42' },
  // The priced models account for the whole priced total.
  unattributed_cost_display: null,
  total_duration_seconds: 1972,
  unknown_duration_phase_count: 0,
  failure_classification: 'unclassified',
  artifact_ids: [MARKDOWN_ARTIFACT_ID, PNG_ARTIFACT_ID],
  deliverable_produced: true,
  review_verdict: 'certified',
  reported_side_effects: 'succeeded',
  repos: [REPO],
  tags: [],
  quarantined_refs: [],
  inputs: {},
  task: 'Add a checked-in fixture set for dashboard screenshots (#1647)',
  skill_use: SKILL_USE,
}

const FAILED_DETAIL: Detail = {
  workflow_execution_id: FAILED_EXECUTION_ID,
  workflow_id: WORKFLOW_ID,
  workflow_name: WORKFLOW_NAME,
  status: 'failed',
  started_at: '2026-11-26T07:10:00Z',
  completed_at: '2026-11-26T07:14:45Z',
  phases: FAILED_PHASES,
  total_phases: 3,
  completed_phases: 1,
  phase_progress: progressOf('failed', FAILED_PHASES),
  phase_plan: planOf(FAILED_PHASES),
  ...cacheRatesOf(modelsRun(FAILED_PHASES)),
  ...sumTokens(FAILED_PHASES),
  total_cost_usd: '1.08',
  unpriced_observation_count: 0,
  total_cost_display: '$1.08',
  cost_by_model: { [OPUS]: '0.97', [SONNET]: '0.11' },
  cost_by_model_display: { [OPUS]: '$0.97', [SONNET]: '$0.11' },
  unattributed_cost_display: null,
  total_duration_seconds: 285,
  artifact_ids: [],
  unknown_duration_phase_count: 0,
  deliverable_produced: false,
  error_message: 'Phase implement failed: just preflight-agent failed: 2 fitness checks red',
  failure_classification: 'gate',
  reported_failure_reason: 'task',
  repos: [REPO],
  tags: [],
  quarantined_refs: [],
  inputs: {},
  task: 'Ratchet untyped-dicts in syn-api',
  skill_use: SKILL_USE,
}

const RUNNING_DETAIL: Detail = {
  workflow_execution_id: RUNNING_EXECUTION_ID,
  workflow_id: WORKFLOW_ID,
  workflow_name: WORKFLOW_NAME,
  status: 'running',
  started_at: '2026-11-26T10:00:00Z',
  completed_at: null,
  phases: RUNNING_PHASES,
  total_phases: 3,
  completed_phases: 0,
  phase_progress: progressOf('running', RUNNING_PHASES),
  phase_plan: planOf(RUNNING_PHASES),
  ...cacheRatesOf(modelsRun(RUNNING_PHASES)),
  ...sumTokens(RUNNING_PHASES),
  total_cost_usd: '0.21',
  unpriced_observation_count: 0,
  total_cost_display: '$0.21',
  cost_by_model: {},
  cost_by_model_display: {},
  // The running phase's cost has no per-model split yet (model_breakdown_text).
  unattributed_cost_display: '$0.21',
  artifact_ids: [],
  unknown_duration_phase_count: 0,
  failure_classification: 'unclassified',
  deliverable_produced: false,
  repos: [REPO],
  tags: [],
  quarantined_refs: [],
  inputs: {},
  task: 'Document the screenshot fixtures in the dashboard README',
  skill_use: SKILL_USE,
}

const DETAILS = [COMPLETED_DETAIL, FAILED_DETAIL, RUNNING_DETAIL]

function summaryOf(d: Detail): Schemas['ExecutionSummaryResponse'] {
  const toolCalls: Record<string, number> = {
    [COMPLETED_EXECUTION_ID]: 212,
    [FAILED_EXECUTION_ID]: 47,
    [RUNNING_EXECUTION_ID]: 9,
  }
  const duration = d.total_duration_seconds ?? null
  return {
    workflow_execution_id: d.workflow_execution_id,
    workflow_id: d.workflow_id,
    workflow_name: d.workflow_name,
    status: d.status,
    started_at: d.started_at,
    completed_at: d.completed_at,
    completed_phases: d.completed_phases,
    total_phases: d.total_phases,
    phase_progress: d.phase_progress,
    total_tokens: d.total_tokens,
    total_tokens_display: formatTokens(d.total_tokens),
    total_input_tokens: d.total_input_tokens,
    total_output_tokens: d.total_output_tokens,
    total_cache_creation_tokens: d.total_cache_creation_tokens,
    total_cache_read_tokens: d.total_cache_read_tokens,
    total_cost_usd: d.total_cost_usd,
    total_cost_display: d.total_cost_display,
    unpriced_observation_count: d.unpriced_observation_count,
    duration_seconds: duration,
    duration_display: formatDuration(duration),
    tool_call_count: toolCalls[d.workflow_execution_id] ?? 0,
    error_message: d.error_message,
    failure_classification: d.failure_classification,
    reported_failure_reason: d.reported_failure_reason,
    review_verdict: d.review_verdict,
    repos: d.repos,
    repos_display: d.repos?.join(', ') ?? null,
    task: d.task,
    task_display: d.task,
  }
}

/** `format_tokens` in syn_shared.display.formatters. */
function formatTokens(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}k`
  return String(n)
}

/** `format_duration_seconds` in syn_shared.display.formatters. */
function formatDuration(seconds: number | null): string {
  if (seconds === null) return '—'
  if (seconds < 1) return '<1s'
  const total = Math.floor(seconds)
  if (total < 60) return `${total}s`
  const minutes = Math.floor(total / 60)
  const secs = total % 60
  if (minutes < 60) return secs ? `${minutes}m ${secs}s` : `${minutes}m`
  const hours = Math.floor(minutes / 60)
  const mins = minutes % 60
  return mins ? `${hours}h ${mins}m` : `${hours}h`
}

const EXECUTION_LIST: Schemas['ExecutionListResponse'] = {
  executions: DETAILS.map(summaryOf),
  total: DETAILS.length,
  page: 1,
  page_size: 50,
  excluded_undated: 0,
  budget: { running: 1, queued: 0, limit: 20, admission_paused: false, display: '1 running / 20' },
  status_counts: { completed: 1, failed: 1, running: 1 },
}

// ---------------------------------------------------------------------------
// Sessions: one per phase that ran.
// ---------------------------------------------------------------------------

interface SessionSeed {
  id: string
  execution: Detail
  phase: Phase
}

const SESSION_SEEDS: SessionSeed[] = DETAILS.flatMap((execution) =>
  (execution.phases ?? []).flatMap((p) => (p.session_id ? [{ id: p.session_id, execution, phase: p }] : [])),
)

function sessionStatus(p: Phase): string {
  return p.status === 'running' ? 'running' : p.status === 'failed' ? 'failed' : 'completed'
}

function sessionSummaryOf({ id, execution, phase: p }: SessionSeed): Schemas['SessionSummaryResponse'] {
  const duration = p.duration_seconds ?? null
  return {
    id,
    workflow_id: execution.workflow_id,
    workflow_name: execution.workflow_name,
    execution_id: execution.workflow_execution_id,
    phase_id: p.phase_id,
    phase_name: p.name,
    phase_display: p.name,
    status: sessionStatus(p),
    agent_provider: p.agent_provider ?? null,
    agent_model: p.model ?? null,
    requested_model: p.requested_model,
    repos: execution.repos,
    repos_display: execution.repos?.join(', ') ?? null,
    input_tokens: p.input_tokens,
    output_tokens: p.output_tokens,
    cache_creation_tokens: p.cache_creation_tokens,
    cache_read_tokens: p.cache_read_tokens,
    total_tokens: p.total_tokens,
    total_tokens_display: formatTokens(p.total_tokens),
    total_cost_usd: p.cost_usd,
    total_cost_display: p.cost_display,
    unpriced_observation_count: p.unpriced_observation_count,
    duration_seconds: duration,
    duration_display: formatDuration(duration),
    started_at: p.started_at,
    completed_at: p.completed_at,
    agent_model_display: p.model_display,
  }
}

const PLAN_OPERATIONS: Schemas['OperationInfo'][] = [
  {
    operation_id: 'op-1',
    operation_type: 'tool_execution_completed',
    timestamp: '2026-11-26T09:00:12Z',
    duration_seconds: 0.4,
    success: true,
    tool_name: 'Read',
    tool_use_id: 'toolu_01',
    tool_input: { file_path: 'apps/syn-dashboard-ui/scripts/screenshot.mjs' },
  },
  {
    operation_id: 'op-2',
    operation_type: 'tool_execution_completed',
    timestamp: '2026-11-26T09:01:03Z',
    duration_seconds: 2.1,
    success: true,
    tool_name: 'Bash',
    tool_use_id: 'toolu_02',
    tool_input: { command: 'git log --oneline -3 -- apps/syn-dashboard-ui' },
  },
  {
    operation_id: 'op-3',
    operation_type: 'git_commit',
    timestamp: '2026-11-26T09:03:40Z',
    success: true,
    git_sha: '4b1c9e2',
    git_message: 'docs: plan for #1647 slice 1',
    git_branch: 'feat/1647-screenshot-fixtures',
    git_repo: REPO,
  },
]

function sessionDetailOf(seed: SessionSeed): Schemas['SessionResponse'] {
  const s = sessionSummaryOf(seed)
  const p = seed.phase
  return {
    ...s,
    agent_model: p.model ?? null,
    milestone_id: null,
    agent_launch: 'launched',
    input_tokens_display: formatTokens(p.input_tokens),
    output_tokens_display: formatTokens(p.output_tokens),
    cache_creation_tokens_display: formatTokens(p.cache_creation_tokens),
    cache_read_tokens_display: formatTokens(p.cache_read_tokens),
    cost_by_model: p.cost_by_model,
    cost_by_model_display: p.cost_by_model_display ?? {},
    unattributed_cost_display: unattributedOf(p.cost_by_model ?? {}, p.cost_usd),
    // routes/sessions.py picks the models the same way `_models_run` does.
    ...cacheRatesOf(modelsRun([p])),
    operations: seed.id === PLAN_SESSION_ID ? PLAN_OPERATIONS : [],
    error_message: p.error_message,
  }
}

const SESSION_LIST: Schemas['SessionListResponse'] = {
  sessions: SESSION_SEEDS.map(sessionSummaryOf),
  total: SESSION_SEEDS.length,
  page: 1,
  page_size: 100,
  excluded_undated: 0,
  status_counts: { completed: 4, failed: 1, running: 1 },
}

// ---------------------------------------------------------------------------
// Artifacts: the plan phase's markdown and the implement phase's screenshot.
// ---------------------------------------------------------------------------

const PLAN_MARKDOWN = [
  '# Plan: screenshot fixtures (#1647)',
  '',
  '1. Build one fixture world typed from the generated API types.',
  '2. Write it to `fixtures/screenshot.json` and check it for drift.',
  '3. Check every fixture route against the OpenAPI spec.',
  '',
  '| Page | Fixture |',
  '| --- | --- |',
  '| `/executions` | 3 runs |',
  '| `/sessions` | 6 sessions |',
].join('\n')

const MARKDOWN_ARTIFACT: Schemas['ArtifactResponse'] = {
  id: MARKDOWN_ARTIFACT_ID,
  workflow_id: WORKFLOW_ID,
  phase_id: 'plan',
  session_id: PLAN_SESSION_ID,
  artifact_type: 'markdown',
  is_primary_deliverable: true,
  content: PLAN_MARKDOWN,
  content_type: 'text/markdown',
  size_bytes: PLAN_MARKDOWN.length,
  title: 'plan.md',
  derived_from: [],
  metadata: {},
  created_at: '2026-11-26T09:04:14Z',
  agent_provider: 'claude',
  agent_model: OPUS,
}

const PNG_ARTIFACT: Schemas['ArtifactResponse'] = {
  id: PNG_ARTIFACT_ID,
  workflow_id: WORKFLOW_ID,
  phase_id: 'implement',
  session_id: IMPLEMENT_SESSION_ID,
  artifact_type: 'image',
  is_primary_deliverable: false,
  // Binary content is served by /artifacts/{id}/raw, which no JSON fixture can answer.
  content: null,
  content_type: 'image/png',
  size_bytes: 184320,
  title: 'dashboard-1280x800.png',
  derived_from: [MARKDOWN_ARTIFACT_ID],
  metadata: {},
  created_at: '2026-11-26T09:26:12Z',
  agent_provider: 'claude',
  agent_model: SONNET,
}

const ARTIFACTS = [MARKDOWN_ARTIFACT, PNG_ARTIFACT]

const ARTIFACT_LIST: Schemas['ArtifactListResponse'] = {
  artifacts: ARTIFACTS.map((a) => ({
    id: a.id,
    workflow_id: a.workflow_id,
    execution_id: COMPLETED_EXECUTION_ID,
    session_id: a.session_id,
    phase_id: a.phase_id,
    artifact_type: a.artifact_type,
    title: a.title,
    size_bytes: a.size_bytes,
    created_at: a.created_at,
    agent_provider: a.agent_provider,
    agent_model: a.agent_model,
  })),
  total: ARTIFACTS.length,
  page: 1,
  page_size: 50,
  excluded_undated: 0,
  type_counts: { markdown: 1, image: 1 },
}

// ---------------------------------------------------------------------------
// Workflows and dashboard metrics.
// ---------------------------------------------------------------------------

const WORKFLOW: Schemas['WorkflowResponse'] = {
  id: WORKFLOW_ID,
  name: WORKFLOW_NAME,
  description: 'Plan, implement and review a change on a feature branch.',
  workflow_type: 'sdlc',
  classification: 'standard',
  phases: PHASES.map(({ phase_id, name }, order) => ({
    phase_id,
    name,
    order,
    agent_type: 'claude',
    timeout_seconds: 3600,
    allow_delegation: false,
    require_delegation: false,
    clone_repos: true,
    delivers_repo_changes: phase_id === 'implement',
    platform_access: 'read',
    requires_verdict: phase_id === 'review',
    kind: 'agent',
    sandbox: 'full-access',
    execution_type: 'sequential',
  })),
  input_declarations: [{ name: 'task', description: 'What to change', required: true }],
  runs_count: DETAILS.length,
  repos: [REPO],
  requires_repos: true,
  tags: ['sdlc'],
}

const WORKFLOW_LIST: Schemas['WorkflowListResponse'] = {
  workflows: [
    {
      id: WORKFLOW.id,
      name: WORKFLOW.name,
      workflow_type: WORKFLOW.workflow_type,
      classification: WORKFLOW.classification,
      description: WORKFLOW.description ?? null,
      phase_count: PHASES.length,
      runs_count: WORKFLOW.runs_count,
      is_archived: false,
      requires_repos: WORKFLOW.requires_repos,
      tags: WORKFLOW.tags,
    },
  ],
  total: 1,
  page: 1,
  page_size: 20,
}

const WORKFLOW_RUNS: Schemas['ExecutionRunListResponse'] = {
  runs: DETAILS.map((d) => ({
    workflow_execution_id: d.workflow_execution_id,
    workflow_id: d.workflow_id,
    workflow_name: d.workflow_name,
    status: d.status,
    started_at: d.started_at,
    completed_at: d.completed_at,
    completed_phases: d.completed_phases,
    total_phases: d.total_phases,
    phase_progress: d.phase_progress,
    total_tokens: d.total_tokens,
    total_cost_usd: d.total_cost_usd,
    total_cost_display: d.total_cost_display,
    unpriced_observation_count: d.unpriced_observation_count,
    error_message: d.error_message,
    failure_classification: d.failure_classification,
    reported_failure_reason: d.reported_failure_reason,
  })),
  total: DETAILS.length,
  workflow_id: WORKFLOW_ID,
  workflow_name: WORKFLOW_NAME,
}

const ALL_TOKENS = sumTokens(DETAILS.flatMap((d) => d.phases ?? []))

/** When the world is read: five minutes into the running execution's plan phase. */
const WORLD_NOW = '2026-11-26T10:05:00Z'

/** `format_cost` (syn_shared.display.formatters) for the amounts this world holds. */
function formatCost(cents: number, unpriced: number): string {
  const known = `$${(cents / 100).toFixed(2)}`
  if (unpriced <= 0) return known
  return cents <= 0 ? 'unpriced' : `>=${known} (partial)`
}

/**
 * One phase across EVERY execution of the workflow, as `/metrics?workflow_id=`
 * builds it (routes/metrics.py `_build_phase_metrics`):
 * - tokens and artifacts from completed runs only
 *   (`WorkflowPhaseMetricsProjection.on_phase_completed`);
 * - running while any execution still runs it, else how the latest run ended,
 *   and the finished runs' time plus each live run's elapsed time
 *   (`PhaseMetricsEntry.status` / `duration_seconds`);
 * - cost summed across executions (`_phase_costs`).
 */
function phaseMetricsOf(phase_id: string, phase_name: string): Schemas['PhaseMetrics'] {
  const runs = DETAILS.flatMap((d) => (d.phases ?? []).filter((p) => p.phase_id === phase_id)).sort((a, b) =>
    (a.started_at ?? '').localeCompare(b.started_at ?? ''),
  )
  const completed = runs.filter((p) => p.status === 'completed')
  const finished = runs.filter((p) => p.status !== 'running')
  const live = runs.filter((p) => p.status === 'running')
  const settled = finished.at(-1)?.status ?? 'failed'
  const inFlight = live.reduce((n, p) => n + (Date.parse(WORLD_NOW) - Date.parse(p.started_at ?? WORLD_NOW)) / 1000, 0)
  const cents = runs.reduce((n, p) => n + Math.round(Number(p.cost_usd) * 100), 0)
  const unpriced = runs.reduce((n, p) => n + p.unpriced_observation_count, 0)
  return {
    phase_id,
    phase_name,
    status: live.length > 0 ? 'running' : settled,
    input_tokens: completed.reduce((n, p) => n + p.input_tokens, 0),
    output_tokens: completed.reduce((n, p) => n + p.output_tokens, 0),
    total_tokens: completed.reduce((n, p) => n + p.total_tokens, 0),
    // `canonical_cost_usd` writes no trailing zeros: `0`, not `0.00`.
    cost_usd: String(cents / 100),
    unpriced_observation_count: unpriced,
    cost_display: formatCost(cents, unpriced),
    cost_in_progress: live.length > 0,
    duration_seconds: finished.reduce((n, p) => n + (p.duration_seconds ?? 0), 0) + inFlight,
    artifact_count: completed.filter((p) => p.artifact_id).length,
  }
}

const METRICS: Schemas['MetricsResponse'] = {
  total_workflows: 1,
  completed_workflows: 1,
  failed_workflows: 1,
  execution_status_counts: { not_started: 0, running: 1, completed: 1, failed: 1, cancelled: 0, interrupted: 0 },
  total_sessions: SESSION_SEEDS.length,
  total_input_tokens: ALL_TOKENS.total_input_tokens,
  total_output_tokens: ALL_TOKENS.total_output_tokens,
  total_cache_creation_tokens: ALL_TOKENS.total_cache_creation_tokens,
  total_cache_read_tokens: ALL_TOKENS.total_cache_read_tokens,
  total_tokens: ALL_TOKENS.total_tokens,
  // 2.26 + 1.08 + 0.21, with the completed run's 4 unpriced observations.
  total_cost_usd: '3.55',
  total_cost_display: '>=$3.55 (partial)',
  unpriced_observation_count: 4,
  total_artifacts: ARTIFACTS.length,
  total_artifact_bytes: ARTIFACTS.reduce((n, a) => n + (a.size_bytes ?? 0), 0),
  // The workflow page reads these; the query string (workflow_id) is ignored.
  phases: PHASES.map(({ phase_id, name }) => phaseMetricsOf(phase_id, name)),
}

const RECENT_COMMITS: Schemas['EventListResponse'] = {
  events: [
    {
      time: '2026-11-26T09:25:50Z',
      event_type: 'git_commit',
      session_id: IMPLEMENT_SESSION_ID,
      execution_id: COMPLETED_EXECUTION_ID,
      phase_id: 'implement',
      data: { sha: '9d3f0a1', message: 'feat(dashboard-ui): screenshot fixture world', repo: REPO },
    },
  ],
  count: 1,
  has_more: false,
}

/** `build_summary` (routes/executions/inventory_summary.py) before any revision is published. */
function inventoryOf(executionId: string): Schemas['SessionInventoryResponse'] {
  return {
    run: { source_instance_id: 'local', execution_id: executionId },
    snapshot: null,
    reconstruction_status: 'not_started',
    observed_evidence_watermark: 0,
    later_evidence_pending: false,
    job_id: null,
    summary: {
      complete: false,
      coverage_state: 'unknown',
      coverage_display: 'unknown: no inventory revision is published yet',
      revision: null,
      distinct_sessions: null,
      platform_sessions: null,
      invocations: null,
      native_transcripts: null,
      gaps: null,
      namespaces: null,
      counts_display: 'No published inventory (reconstruction not started)',
      remote_replication: 'disabled',
      follow_up_command: `syn execution sessions ${executionId} --all`,
    },
  }
}

/** The deprecated history route answers an empty list for every workflow (routes/workflows/queries.py). */
const WORKFLOW_HISTORY: Schemas['ExecutionHistoryResponse'] = {
  workflow_id: WORKFLOW_ID,
  workflow_name: WORKFLOW_NAME,
  executions: [],
  total_executions: 0,
}

/**
 * The world's one day of activity, from the same canonical usage the global
 * metrics read (#932): every session ran on 2026-11-26, so the day holds all
 * four token categories of all of them (`_build_day_breakdown`,
 * TimescaleHeatmapQuery.py), and its cost is the global total. There is no
 * earlier history: a day of usage the global metrics did not count would make
 * the dashboard quote two totals for one world.
 */
const HEATMAP_DAYS: Schemas['HeatmapDayBucketResponse'][] = [
  {
    date: '2026-11-26',
    count: SESSION_SEEDS.length,
    breakdown: {
      sessions: SESSION_SEEDS.length,
      executions: DETAILS.length,
      commits: RECENT_COMMITS.events.length,
      cost_usd: Number(METRICS.total_cost_usd),
      tokens:
        METRICS.total_input_tokens +
        METRICS.total_output_tokens +
        METRICS.total_cache_creation_tokens +
        METRICS.total_cache_read_tokens,
      input_tokens: METRICS.total_input_tokens,
      output_tokens: METRICS.total_output_tokens,
      cache_creation_tokens: METRICS.total_cache_creation_tokens,
      cache_read_tokens: METRICS.total_cache_read_tokens,
      // The review phase's codex tokens were not priced (_heatmap_cost_display).
      unpriced_tokens: COMPLETED_PHASES[2].total_tokens,
    },
    cost_display: METRICS.total_cost_display,
    failed: 1,
  },
]

const HEATMAP: Schemas['ContributionHeatmapResponse'] = {
  metric: 'sessions',
  start_date: '2025-11-26',
  end_date: '2026-11-26',
  total: HEATMAP_DAYS.reduce((n, d) => n + d.count, 0),
  total_cost_display: METRICS.total_cost_display,
  days: HEATMAP_DAYS,
  filter: {},
}

// ---------------------------------------------------------------------------
// The world.
// ---------------------------------------------------------------------------

export const SCREENSHOT_FIXTURES: readonly ScreenshotFixture[] = [
  fixture('/health', {}, HEALTH),
  fixture('/version', {}, BUILD),
  fixture('/features', {}, { ui_feedback: false }),
  fixture('/metrics', {}, METRICS),
  fixture('/events/recent', {}, RECENT_COMMITS),
  fixture('/workflows', {}, WORKFLOW_LIST),
  fixture('/workflows/{workflow_id}', { workflow_id: WORKFLOW_ID }, WORKFLOW),
  fixture('/workflows/{workflow_id}/runs', { workflow_id: WORKFLOW_ID }, WORKFLOW_RUNS),
  fixture('/workflows/{workflow_id}/history', { workflow_id: WORKFLOW_ID }, WORKFLOW_HISTORY),
  fixture('/insights/contribution-heatmap', {}, HEATMAP),
  fixture('/executions', {}, EXECUTION_LIST),
  ...DETAILS.map((d) =>
    fixture('/executions/{execution_id}', { execution_id: d.workflow_execution_id }, d),
  ),
  ...DETAILS.map((d) =>
    fixture(
      '/executions/{execution_id}/session-inventory',
      { execution_id: d.workflow_execution_id },
      inventoryOf(d.workflow_execution_id),
    ),
  ),
  // The query string carries the execution id, so one answer serves all three.
  fixture('/capture/status', {}, {
    total: 0,
    needs_backfill_count: 0,
    unattributable_count: 0,
    scanned: 0,
    truncated: false,
    entries: [],
    capabilities: [],
  }),
  fixture('/sessions', {}, SESSION_LIST),
  ...SESSION_SEEDS.map((seed) => fixture('/sessions/{session_id}', { session_id: seed.id }, sessionDetailOf(seed))),
  fixture('/artifacts', {}, ARTIFACT_LIST),
  ...ARTIFACTS.map((a) => fixture('/artifacts/{artifact_id}', { artifact_id: a.id }, a)),
]

/** The `--fixtures` file: request pathname to response body, in a stable order. */
export function screenshotFixturesJson(fixtures: readonly ScreenshotFixture[] = SCREENSHOT_FIXTURES): string {
  const byPathname: Record<string, unknown> = {}
  for (const { pathname, body } of fixtures) {
    if (pathname in byPathname) throw new Error(`two screenshot fixtures answer ${pathname}`)
    byPathname[pathname] = body
  }
  return `${JSON.stringify(byPathname, null, 2)}\n`
}
