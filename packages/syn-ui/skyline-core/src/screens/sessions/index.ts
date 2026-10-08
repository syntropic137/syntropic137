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
import { shortId } from '../../format/number'
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
export function summarizeToolInput(input: Record<string, unknown> | null | undefined): string {
  if (!input) return ''
  for (const key of ['command', 'cmd', 'file_path', 'path', 'pattern', 'url', 'query', 'description', 'prompt']) {
    const v = input[key]
    if (typeof v === 'string' && v.trim()) return v
    if (Array.isArray(v) && v.every((x) => typeof x === 'string')) return v.join(' ')
  }
  const keys = Object.keys(input)
  if (keys.length === 0) return ''
  return JSON.stringify(input)
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
  const clock = (t: string | null | undefined) => operationClock(t, options)

  for (const op of sorted) {
    const type = op.operation_type
    if (SKIP_TYPES.has(type)) continue

    if (op.tool_name && (START_TYPES.has(type) || FINISH_TYPES.has(type) || type.startsWith('tool'))) {
      const existing = op.tool_use_id ? openByUse.get(op.tool_use_id) : undefined
      const failed = !op.success || type === 'tool_blocked' || !!op.error_message
      const output = op.tool_output ?? op.error_message ?? null
      if (existing) {
        existing.status = failed ? 'failed' : 'ok'
        if (output) existing.output = output
        const d = durationText(op.duration_seconds)
        if (d) existing.duration = d
        if (!existing.input) existing.input = summarizeToolInput(op.tool_input)
        markDelegation(existing)
        if (op.tool_use_id) openByUse.delete(op.tool_use_id)
        continue
      }
      const row: SessionOperation = {
        id: op.operation_id,
        time: clock(op.timestamp),
        tool: op.tool_name,
        kind: op.tool_name.toLowerCase(),
        isTool: true,
        input: summarizeToolInput(op.tool_input),
        output,
        status: START_TYPES.has(type) ? 'running' : failed ? 'failed' : 'ok',
      }
      const d = durationText(op.duration_seconds)
      if (d) row.duration = d
      markDelegation(row)
      rows.push(row)
      if (START_TYPES.has(type) && op.tool_use_id) openByUse.set(op.tool_use_id, row)
      continue
    }

    if (type.startsWith('git') || op.git_sha) {
      const row: SessionOperation = {
        id: op.operation_id,
        time: clock(op.timestamp),
        tool: type === 'git_push' ? 'Push' : type === 'git_commit' ? 'Commit' : 'Git',
        kind: 'git',
        isTool: false,
        input: [op.git_sha ? op.git_sha.slice(0, 7) : null, op.git_branch, op.git_repo].filter(Boolean).join(' · ') || type,
        output: op.git_message ?? null,
        status: op.success ? 'quiet' : 'failed',
      }
      const url = commitUrl(op.git_repo, op.git_sha)
      if (url) row.commitUrl = url
      rows.push(row)
      continue
    }

    if (op.thinking_content) {
      rows.push({ id: op.operation_id, time: clock(op.timestamp), tool: 'Thinking', kind: 'thinking', isTool: false, input: firstLine(op.thinking_content), output: op.thinking_content, status: 'quiet' })
      continue
    }
    if (op.message_content) {
      const role = op.message_role === 'user' ? 'Prompt' : op.message_role === 'assistant' ? 'Reply' : 'Message'
      rows.push({ id: op.operation_id, time: clock(op.timestamp), tool: role, kind: 'message', isTool: false, input: firstLine(op.message_content), output: op.message_content, status: 'quiet' })
      continue
    }
    if (type === 'error' || !op.success) {
      rows.push({ id: op.operation_id, time: clock(op.timestamp), tool: 'Error', kind: 'error', isTool: false, input: op.error_message ?? type, output: null, status: 'failed' })
    }
  }
  return rows
}

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

/** "8 tool calls from 16 recorded events, oldest first" or "2 of 8 tool calls shown". */
export function operationsSummary(rows: readonly SessionOperation[], shown: number, events: number, filter: OperationFilter): string {
  const tools = rows.filter((r) => r.isTool).length
  const noun = (n: number) => (n === 1 ? 'tool call' : 'tool calls')
  if (filter !== 'all') return `${shown} of ${rows.length} ${rows.length === 1 ? 'operation' : 'operations'} shown`
  return `${tools} ${noun(tools)} from ${events} recorded ${events === 1 ? 'event' : 'events'}, oldest first`
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

/** "Codex · gpt-5.6-sol"; the model string renders verbatim (it may be "unknown (requested: opus)"). */
export function agentLabel(provider: string | null | undefined, modelDisplay: string | null | undefined): string {
  const p = provider ? (PROVIDER_LABEL[provider.toLowerCase()] ?? provider) : null
  return [p, modelDisplay].filter(Boolean).join(' · ') || UNKNOWN
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
  agent_model_display?: string | null
  repos_display?: string | null
  status: string
  total_tokens_display?: string | null
  total_cost_display?: string | null
  duration_display?: string | null
}

/** "build-and-delegate · Codex · gpt-5.6-sol · syntropic137/syntropic137" (mono line under a list row). */
export function sessionRowSub(s: SessionRowInput): string {
  return [s.phase_display || s.phase_id || null, agentLabel(s.agent_provider, s.agent_model_display), s.repos_display || null].filter((x) => x && x !== UNKNOWN).join(' · ')
}

/** Markdown an agent can act on: one bullet per session with its id, workflow, phase, status and spend. */
export function sessionsForAgent(rows: readonly SessionRowInput[]): string {
  return rows
    .map((s) => `- session ${s.id}: ${s.workflow_name ?? s.workflow_id ?? 'unknown workflow'} / ${s.phase_display ?? s.phase_id ?? 'no phase'} · ${s.status} · ${s.total_tokens_display ?? UNKNOWN} tokens · ${s.total_cost_display ?? UNKNOWN} · ${s.duration_display ?? UNKNOWN}`)
    .join('\n')
}
