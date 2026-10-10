/**
 * Session screens (Session, PhoneSession boards; the Sessions list follows the
 * Executions list language). Pure logic only: turning the API's raw operation
 * events into timeline rows, the filter chips, the usage meter inputs, the
 * breadcrumb trail, and the visible window of a long list.
 *
 * Structural input types (`SessionOperationInput`, `SessionLike`) mirror the
 * fields of the API's OperationInfo / SessionResponse that these functions
 * read, so core stays free of the data package.
 */
import { formatCostPrecise } from '../../format/cost'
import { formatDurationPrecise } from '../../format/duration'
import { UNKNOWN, toNumber } from '../../format/shared'
import { formatInteger, shortId } from '../../format/number'
import type { TokenBreakdown } from '../../format/tokens'
import type { Operation, OperationStatus } from '../../patterns/operations'
import type { CostRowInput } from '../../patterns/usage'
import type { Crumb } from '../../patterns/types'

export interface SessionOperationInput {
  operation_id: string
  operation_type: string
  timestamp?: string | null
  duration_seconds?: number | null
  success: boolean
  error_message?: string | null
  total_tokens?: number | null
  tool_name?: string | null
  tool_use_id?: string | null
  tool_input?: Record<string, unknown> | null
  tool_output?: string | null
  message_role?: string | null
  message_content?: string | null
  thinking_content?: string | null
  git_sha?: string | null
  git_message?: string | null
  git_branch?: string | null
  git_repo?: string | null
}

/** A timeline row plus the facts the filter chips need. */
export interface SessionOperation extends Operation {
  /** Lowercased tool name, or "message" / "thinking" / "git" for non-tool rows. */
  kind: string
  /** True for tool calls (counted in "8 tool calls"). */
  isTool: boolean
  /** Link to the commit on GitHub, for git rows. */
  commitUrl?: string
}

const START_TYPES = new Set(['tool_execution_started', 'tool_started', 'tool_use'])
const FINISH_TYPES = new Set(['tool_execution_completed', 'tool_completed', 'tool_result', 'tool_execution', 'tool_blocked'])
const SKIP_TYPES = new Set(['token_usage', 'session_started', 'session_completed'])

/** The most useful one-line summary of a tool input: the command, the path, the pattern, else compact JSON. */
const SUMMARY_KEYS = ['command', 'cmd', 'file_path', 'path', 'pattern', 'url', 'query', 'description', 'prompt', 'skill'] as const

/** A recorder that could not parse the input keeps it as `{ raw: "<json>" }`, often cut short: read the first summary key out of it. */
function summarizeRaw(raw: string): string | undefined {
  try {
    const parsed: unknown = JSON.parse(raw)
    if (parsed && typeof parsed === 'object' && !Array.isArray(parsed)) return summarizeToolInput(parsed as Record<string, unknown>) || undefined
  } catch {
    // Truncated JSON: fall through to the key scan.
  }
  for (const key of SUMMARY_KEYS) {
    const m = new RegExp(`"${key}"\\s*:\\s*"((?:[^"\\\\]|\\\\.)*)"`).exec(raw)
    if (m) {
      try {
        const v = JSON.parse(`"${m[1]}"`) as string
        if (v.trim()) return v
      } catch {
        // Not a valid string literal; try the next key.
      }
    }
  }
  return undefined
}

/** The first summary key with a usable string (or string list) value. */
function summaryKeyValue(input: Record<string, unknown>): string | undefined {
  for (const key of SUMMARY_KEYS) {
    const v = input[key]
    if (typeof v === 'string' && v.trim()) return v
    if (Array.isArray(v) && v.every((x) => typeof x === 'string')) return v.join(' ')
  }
  return undefined
}

export function summarizeToolInput(input: Record<string, unknown> | null | undefined): string {
  if (!input) return ''
  const fromRaw = typeof input.raw === 'string' && Object.keys(input).length === 1 ? summarizeRaw(input.raw) : undefined
  const found = fromRaw ?? summaryKeyValue(input)
  if (found) return found
  return Object.keys(input).length === 0 ? '' : JSON.stringify(input)
}

function durationText(seconds: number | null | undefined): string | undefined {
  if (seconds === null || seconds === undefined || !Number.isFinite(seconds) || seconds < 0) return undefined
  if (seconds < 1) return '0s'
  if (seconds < 60) return `${Math.round(seconds)}s`
  return formatDurationPrecise(seconds * 1000)
}

/** "https://github.com/owner/repo/commit/sha" when the repo is "owner/repo" or a GitHub URL. */
export function commitUrl(repo: string | null | undefined, sha: string | null | undefined): string | undefined {
  if (!repo || !sha) return undefined
  const bare = repo.replace(/^https?:\/\/github\.com\//, '').replace(/\.git$/, '').replace(/\/$/, '')
  if (!/^[\w.-]+\/[\w.-]+$/.test(bare)) return undefined
  return `https://github.com/${bare}/commit/${sha}`
}

const CHILD_SESSION = /"session_id"\s*:\s*"([0-9a-f-]{8,})"/i

/**
 * Raw events to timeline rows, oldest first. A tool start and its finish
 * (same tool_use_id) merge into one row; messages, thinking and git events
 * become quiet rows; bookkeeping events (token_usage, session_*) drop.
 * A Bash call that runs `claude -p` or `codex exec` and reports a session
 * id is marked as a hand-off.
 */
export function sessionOperations(ops: readonly SessionOperationInput[], options: { timeZone?: string } = {}): SessionOperation[] {
  const sorted = [...ops].sort((a, b) => (Date.parse(a.timestamp ?? '') || 0) - (Date.parse(b.timestamp ?? '') || 0))
  const rows: SessionOperation[] = []
  const openByUse = new Map<string, SessionOperation>()
  const clock: OperationClock = (t) => operationClock(t, options)

  for (const op of sorted) {
    if (SKIP_TYPES.has(op.operation_type)) continue
    const row = isToolEvent(op) ? applyToolEvent(op, openByUse, clock) : quietRow(op, clock)
    if (row) rows.push(row)
  }
  return rows
}

type OperationClock = (t: string | null | undefined) => string
type ToolEvent = SessionOperationInput & { tool_name: string }

function isToolEvent(op: SessionOperationInput): op is ToolEvent {
  const type = op.operation_type
  return !!op.tool_name && (START_TYPES.has(type) || FINISH_TYPES.has(type) || type.startsWith('tool'))
}

function toolFailed(op: SessionOperationInput): boolean {
  return !op.success || op.operation_type === 'tool_blocked' || !!op.error_message
}

function toolOutput(op: SessionOperationInput): string | null {
  return op.tool_output ?? op.error_message ?? null
}

/** Merges a finish into its open start (returns undefined), or returns a new row. */
function applyToolEvent(op: ToolEvent, openByUse: Map<string, SessionOperation>, clock: OperationClock): SessionOperation | undefined {
  const useId = op.tool_use_id
  const existing = useId ? openByUse.get(useId) : undefined
  if (useId && existing) {
    finishToolRow(existing, op)
    openByUse.delete(useId)
    return undefined
  }
  const row = startToolRow(op, clock)
  if (START_TYPES.has(op.operation_type) && useId) openByUse.set(useId, row)
  return row
}

function finishToolRow(row: SessionOperation, op: SessionOperationInput): void {
  const output = toolOutput(op)
  row.status = toolFailed(op) ? 'failed' : 'ok'
  if (output) row.output = output
  const d = durationText(op.duration_seconds)
  if (d) row.duration = d
  if (!row.input) row.input = summarizeToolInput(op.tool_input)
  markDelegation(row)
}

function toolStartStatus(op: SessionOperationInput): OperationStatus {
  if (START_TYPES.has(op.operation_type)) return 'running'
  return toolFailed(op) ? 'failed' : 'ok'
}

function startToolRow(op: ToolEvent, clock: OperationClock): SessionOperation {
  const row: SessionOperation = {
    id: op.operation_id,
    time: clock(op.timestamp),
    tool: op.tool_name,
    kind: op.tool_name.toLowerCase(),
    isTool: true,
    input: summarizeToolInput(op.tool_input),
    output: toolOutput(op),
    status: toolStartStatus(op),
  }
  const d = durationText(op.duration_seconds)
  if (d) row.duration = d
  markDelegation(row)
  return row
}

type QuietRowBuilder = (op: SessionOperationInput, clock: OperationClock) => SessionOperation | undefined

/** Non-tool rows, first match wins: git, thinking, message, error. */
function quietRow(op: SessionOperationInput, clock: OperationClock): SessionOperation | undefined {
  for (const build of QUIET_ROW_BUILDERS) {
    const row = build(op, clock)
    if (row) return row
  }
  return undefined
}

const GIT_TOOL = new Map([
  ['git_push', 'Push'],
  ['git_commit', 'Commit'],
])

function gitInput(op: SessionOperationInput): string {
  const sha = op.git_sha ? op.git_sha.slice(0, 7) : null
  return [sha, op.git_branch, op.git_repo].filter(Boolean).join(' · ') || op.operation_type
}

const gitRow: QuietRowBuilder = (op, clock) => {
  const type = op.operation_type
  if (!type.startsWith('git') && !op.git_sha) return undefined
  const row: SessionOperation = {
    id: op.operation_id,
    time: clock(op.timestamp),
    tool: GIT_TOOL.get(type) ?? 'Git',
    kind: 'git',
    isTool: false,
    input: gitInput(op),
    output: op.git_message ?? null,
    status: op.success ? 'quiet' : 'failed',
  }
  const url = commitUrl(op.git_repo, op.git_sha)
  if (url) row.commitUrl = url
  return row
}

const thinkingRow: QuietRowBuilder = (op, clock) => {
  if (!op.thinking_content) return undefined
  return { id: op.operation_id, time: clock(op.timestamp), tool: 'Thinking', kind: 'thinking', isTool: false, input: firstLine(op.thinking_content), output: op.thinking_content, status: 'quiet' }
}

const MESSAGE_ROLE = new Map([
  ['user', 'Prompt'],
  ['assistant', 'Reply'],
])

const messageRow: QuietRowBuilder = (op, clock) => {
  if (!op.message_content) return undefined
  const role = MESSAGE_ROLE.get(op.message_role ?? '') ?? 'Message'
  return { id: op.operation_id, time: clock(op.timestamp), tool: role, kind: 'message', isTool: false, input: firstLine(op.message_content), output: op.message_content, status: 'quiet' }
}

const errorRow: QuietRowBuilder = (op, clock) => {
  if (op.operation_type !== 'error' && op.success) return undefined
  return { id: op.operation_id, time: clock(op.timestamp), tool: 'Error', kind: 'error', isTool: false, input: op.error_message ?? op.operation_type, output: null, status: 'failed' }
}

const QUIET_ROW_BUILDERS: readonly QuietRowBuilder[] = [gitRow, thinkingRow, messageRow, errorRow]

/** "1:32:22 PM" (Session board); the phone drops the meridiem with `compact`. */
export function operationClock(value: string | null | undefined, options: { timeZone?: string; compact?: boolean } = {}): string {
  const t = value ? Date.parse(value) : NaN
  if (!Number.isFinite(t)) return UNKNOWN
  const text = new Intl.DateTimeFormat('en-US', { hour: 'numeric', minute: '2-digit', second: '2-digit', hour12: true, timeZone: options.timeZone }).format(t)
  return options.compact ? text.replace(/\s?[AP]M$/, '') : text
}

function firstLine(text: string): string {
  const line = text.split('\n').find((l) => l.trim()) ?? ''
  return line.length > 160 ? `${line.slice(0, 159)}…` : line
}

function markDelegation(row: SessionOperation): void {
  if (row.kind !== 'bash') return
  const agent = /(^|[\s;&|])claude\s+-p\b/.test(row.input) ? 'claude' : /(^|[\s;&|])codex\s+exec\b/.test(row.input) ? 'codex' : null
  if (!agent) return
  const id = row.output?.match(CHILD_SESSION)?.[1]
  const name = agent === 'claude' ? 'Claude' : 'Codex'
  row.delegated = id
    ? { agent: name, agentKind: agent, label: `Handed off to ${name} · child session`, id: shortId(id), href: `/sessions/${id}` }
    : { agent: name, agentKind: agent, label: `Handed off to ${name}` }
}

export type OperationFilter = string

export interface OperationChip {
  /** "all", "errors", or a tool kind ("bash"). */
  value: OperationFilter
  label: string
  count: number
}

/** All, then each tool by frequency (at most `maxTools`), then Errors when any failed. */
export function operationChips(rows: readonly SessionOperation[], maxTools = 4): OperationChip[] {
  const counts = new Map<string, { label: string; count: number }>()
  for (const r of rows) {
    if (!r.isTool) continue
    const c = counts.get(r.kind)
    if (c) c.count++
    else counts.set(r.kind, { label: r.tool, count: 1 })
  }
  const tools = [...counts.entries()]
    .sort((a, b) => b[1].count - a[1].count || a[1].label.localeCompare(b[1].label))
    .slice(0, maxTools)
    .map(([value, c]) => ({ value, label: c.label, count: c.count }))
  const errors = rows.filter((r) => r.status === 'failed').length
  const chips: OperationChip[] = [{ value: 'all', label: 'All', count: rows.length }, ...tools]
  if (errors > 0) chips.push({ value: 'errors', label: 'Errors', count: errors })
  return chips
}

export function filterOperations(rows: readonly SessionOperation[], filter: OperationFilter): SessionOperation[] {
  if (filter === 'all') return [...rows]
  if (filter === 'errors') return rows.filter((r) => r.status === 'failed')
  return rows.filter((r) => r.kind === filter)
}

/** "8 tool calls from 16 recorded events, newest first" or "2 of 8 tool calls shown". */
export function operationsSummary(rows: readonly SessionOperation[], shown: number, events: number, filter: OperationFilter): string {
  const tools = rows.filter((r) => r.isTool).length
  const noun = (n: number) => (n === 1 ? 'tool call' : 'tool calls')
  if (filter !== 'all') return `${shown} of ${rows.length} ${rows.length === 1 ? 'operation' : 'operations'} shown`
  return `${tools} ${noun(tools)} from ${events} recorded ${events === 1 ? 'event' : 'events'}, newest first`
}

export function countToolCalls(rows: readonly SessionOperation[]): number {
  return rows.filter((r) => r.isTool).length
}

/** Cost rows for the Usage Meter, largest first; tone follows the provider. */
export function costByModelRows(costByModel: Record<string, string | number> | null | undefined, provider?: string | null): CostRowInput[] {
  const tone = agentKind(provider)
  return Object.entries(costByModel ?? {})
    .map(([label, v]) => ({ label, value: toNumber(v) }))
    .sort((a, b) => (b.value ?? -1) - (a.value ?? -1))
    .map((r) => ({ ...r, tone: tone === 'other' ? 'neutral' : tone }))
}

export function sessionTokens(s: { input_tokens: number; output_tokens: number; cache_creation_tokens?: number | null; cache_read_tokens?: number | null }): TokenBreakdown {
  return { input: s.input_tokens ?? 0, output: s.output_tokens ?? 0, cacheWrite: s.cache_creation_tokens ?? 0, cacheRead: s.cache_read_tokens ?? 0 }
}

/** "$0.2162", or "$0.2162+" with a note when some observations had no price (cost incomplete, #890). */
export function sessionCost(total: number | string | null | undefined, unpriced: number | null | undefined): { display: string; note?: string } {
  const display = formatCostPrecise(total)
  if (!unpriced || unpriced <= 0 || display === UNKNOWN) return { display }
  return { display: `${display}+`, note: `${unpriced} ${unpriced === 1 ? 'observation' : 'observations'} had no price, so the cost is incomplete.` }
}

export function agentKind(provider: string | null | undefined): 'claude' | 'codex' | 'other' {
  const p = (provider ?? '').toLowerCase()
  if (p.includes('claude') || p.includes('anthropic')) return 'claude'
  if (p.includes('codex') || p.includes('openai')) return 'codex'
  return 'other'
}

const PROVIDER_LABEL: Record<string, string> = { claude: 'Claude', codex: 'Codex', anthropic: 'Claude', openai: 'Codex' }

export const MODEL_NOT_REPORTED = 'model not reported'

/**
 * The observed model, verbatim, or "model not reported" (feedback
 * 58868cd8: Codex sessions read "unknown"). Owner rule: only the exact
 * observed model is ever shown, so a null `agent_model`, or the API's
 * "unknown" / "unknown (requested: gpt-sol)" display, never shows a model;
 * the requested alias belongs in a tooltip, not the label.
 */
export function observedModel(model: string | null | undefined, display: string | null | undefined): string | null {
  if (model === null || (display && /^unknown\b/i.test(display.trim()))) return MODEL_NOT_REPORTED
  return display || model || null
}

/** "Codex · gpt-5.6-sol", or "Codex · model not reported" when no model was observed (pass `model` = agent_model). */
export function agentLabel(provider: string | null | undefined, modelDisplay: string | null | undefined, model?: string | null): string {
  const p = provider ? (PROVIDER_LABEL[provider.toLowerCase()] ?? provider) : null
  const m = observedModel(model, modelDisplay)
  return [p, p || m !== MODEL_NOT_REPORTED ? m : null].filter(Boolean).join(' · ') || UNKNOWN
}

export interface SessionCrumbInput {
  id: string
  workflow_id?: string | null
  workflow_name?: string | null
  execution_id?: string | null
  phase_id?: string | null
  phase_display?: string | null
}

/** Workflows › workflow › Execution 6350e65e › phase (Session board); a loose session hangs off Sessions. */
export function sessionCrumbs(s: SessionCrumbInput): Crumb[] {
  const here: Crumb = s.phase_display || s.phase_id ? { label: (s.phase_display || s.phase_id)! } : { label: 'Session', id: shortId(s.id) }
  if (!s.workflow_id && !s.execution_id) return [{ label: 'Sessions', href: '/sessions' }, here]
  const crumbs: Crumb[] = [{ label: 'Workflows', href: '/workflows' }]
  if (s.workflow_id) crumbs.push({ label: s.workflow_name || shortId(s.workflow_id), href: `/workflows/${s.workflow_id}` })
  if (s.execution_id) crumbs.push({ label: 'Execution', id: shortId(s.execution_id), href: `/executions/${s.execution_id}` })
  crumbs.push(here)
  return crumbs
}

/** The transcript exists once the session has finished. */
export function transcriptAvailable(status: string): boolean {
  return status === 'completed' || status === 'failed'
}

export interface WindowInput {
  /** Pixels of the list scrolled past the top of the viewport (0 when the list starts below it). */
  offset: number
  /** Viewport height in pixels. */
  viewport: number
  rowHeight: number
  count: number
  /** Extra rows rendered above and below (default 6). */
  overscan?: number
}

export interface WindowRange {
  start: number
  end: number
  /** Spacer heights that keep the scrollbar honest. */
  padTop: number
  padBottom: number
}

/** Which rows of a fixed-height list intersect the viewport, plus overscan. `end` is exclusive. */
export function windowRange({ offset, viewport, rowHeight, count, overscan = 6 }: WindowInput): WindowRange {
  if (count <= 0 || rowHeight <= 0) return { start: 0, end: 0, padTop: 0, padBottom: 0 }
  const first = Math.floor(Math.max(0, offset) / rowHeight)
  const visible = Math.ceil(Math.max(0, viewport) / rowHeight) + 1
  const start = Math.max(0, Math.min(count - 1, first - overscan))
  const end = Math.min(count, first + visible + overscan)
  return { start, end: Math.max(start, end), padTop: start * rowHeight, padBottom: (count - Math.max(start, end)) * rowHeight }
}

/** Rows to render for a variable-height list revealed in chunks as the reader nears the end. */
export function revealCount(current: number, total: number, chunk = 40): number {
  return Math.min(total, Math.max(0, current) + chunk)
}

export type { OperationStatus }

export interface SessionRowInput {
  id: string
  workflow_name?: string | null
  workflow_id?: string | null
  phase_display?: string | null
  phase_id?: string | null
  agent_provider?: string | null
  agent_model?: string | null
  agent_model_display?: string | null
  repos_display?: string | null
  status: string
  total_tokens_display?: string | null
  total_cost_display?: string | null
  duration_display?: string | null
}

/** "build-and-delegate · Codex · gpt-5.6-sol · syntropic137/syntropic137" (mono line under a list row). */
export function sessionRowSub(s: SessionRowInput): string {
  return [s.phase_display || s.phase_id || null, agentLabel(s.agent_provider, s.agent_model_display, s.agent_model), s.repos_display || null].filter((x) => x && x !== UNKNOWN).join(' · ')
}

/** Markdown an agent can act on: one bullet per session with its id, workflow, phase, status and spend. */
export function sessionsForAgent(rows: readonly SessionRowInput[]): string {
  return rows
    .map((s) => `- session ${s.id}: ${s.workflow_name ?? s.workflow_id ?? 'unknown workflow'} / ${s.phase_display ?? s.phase_id ?? 'no phase'} · ${s.status} · ${s.total_tokens_display ?? UNKNOWN} tokens · ${s.total_cost_display ?? UNKNOWN} · ${s.duration_display ?? UNKNOWN}`)
    .join('\n')
}

const runningNow = (n: number) => (n === 0 ? 'none running' : `${formatInteger(n)} running`)

/** Hero lede (Sessions board): "One agent run per phase, plus any child sessions it hands off to. 118 so far, none running." */
export function sessionsLede(t: { total: number; running: number }): string {
  const lead = 'One agent run per phase, plus any child sessions it hands off to.'
  if (t.total === 0) return `${lead} None yet.`
  return `${lead} ${formatInteger(t.total)} so far, ${runningNow(t.running)}.`
}

/** Phone lede (PhoneSessions board): "118 agent runs, none running now". */
export function sessionsLedeShort(t: { total: number; running: number }): string {
  return `${formatInteger(t.total)} agent ${t.total === 1 ? 'run' : 'runs'}, ${t.running === 0 ? 'none running now' : `${formatInteger(t.running)} running now`}`
}

export interface SessionListRowInput extends SessionRowInput {
  execution_id?: string | null
  parent_session_id?: string | null
}

export interface SessionListRow {
  /** The phase, "(delegated)" for a child session: "review (delegated)". */
  title: string
  delegated: boolean
  /** Mono line under the title: "a41c09e7 · syntropic137", "35468ba1 · child of 2fd5ec12". */
  sub: string
  workflow: string
  /** "exec e93b07d2", or empty. */
  execution: string
  /** "Claude · claude-sonnet-5-5" (observed model only). */
  agent: string
  /** "Claude", or null when no provider was recorded. */
  provider: string | null
  /** The observed model verbatim, or "model not reported". */
  model: string
}

const rowPhase = (s: SessionListRowInput): string => s.phase_display || s.phase_id || s.workflow_name || s.workflow_id || `Session ${shortId(s.id)}`
const rowProvider = (p: string | null | undefined): string | null => (p ? (PROVIDER_LABEL[p.toLowerCase()] ?? p) : null)
const rowSub = (s: SessionListRowInput): string =>
  [shortId(s.id), s.parent_session_id ? `child of ${shortId(s.parent_session_id)}` : s.repos_display || null].filter(Boolean).join(' · ')

/** One Sessions-board row: the phase leads, the workflow and execution sit in their own column. */
export function sessionListRow(s: SessionListRowInput): SessionListRow {
  const delegated = !!s.parent_session_id
  const phase = rowPhase(s)
  return {
    title: delegated ? `${phase} (delegated)` : phase,
    delegated,
    sub: rowSub(s),
    workflow: s.workflow_name || s.workflow_id || 'Unknown workflow',
    execution: s.execution_id ? `exec ${shortId(s.execution_id)}` : '',
    agent: agentLabel(s.agent_provider, s.agent_model_display, s.agent_model),
    provider: rowProvider(s.agent_provider),
    model: observedModel(s.agent_model, s.agent_model_display) ?? MODEL_NOT_REPORTED,
  }
}

export * from './live'

/**
 * A session's duration as the header shows it: the API's `duration_display`
 * verbatim ("1m 59s"), so the detail agrees with the list; only an older
 * server without it gets `formatDurationPrecise` (parity-2: the detail
 * rounded 119.8 s to "2m").
 */
export function sessionDurationText(s: { duration_seconds: number | null; duration_display?: string | null }): string {
  if (s.duration_display) return s.duration_display
  return s.duration_seconds === null ? UNKNOWN : formatDurationPrecise(s.duration_seconds * 1000).replace(/\.0s$/, 's')
}
