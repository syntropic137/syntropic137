/**
 * Execution detail (Execution and PhoneExecution boards): the per-phase
 * lines, chips and captions, the cost-by-phase rows and the provenance
 * strip, worked out from the API's execution and inventory shapes.
 *
 * Inputs are structural (the fields used, not the client's types), so
 * skyline-core stays free of the data package.
 */
import { formatCostPrecise } from '../../format/cost'
import { formatDurationPrecise } from '../../format/duration'
import { formatTokens } from '../../format/tokens'
import { toNumber } from '../../format/shared'
import type { CostRowInput } from '../../patterns/usage'
import type { KitAbsence, ProvenanceStripProps, SkillRefProps } from '../../patterns'
import { statusKind } from '../../patterns/status'

export interface PhaseLike {
  name: string
  status: string
  input_tokens: number
  output_tokens: number
  cache_creation_tokens: number
  cache_read_tokens: number
  duration_seconds: number | null
  /** USD; the live API serialises Decimal as a string, fixtures send a number. */
  cost_usd: number | string
  model: string | null
  requested_model: string | null
  model_display?: string
  /** USD per observed model id, or `unattributed-model`; empty while a phase runs. */
  cost_by_model?: Readonly<Record<string, string | number>> | null
  start_pins_status?: 'recorded' | 'not_recorded' | 'unavailable'
  pinned_at_start?: {
    provider: string
    requested_model?: string | null
    allowed_tools?: string[]
    skills?: { name: string; version: string; resolved_sha: string; source_url: string }[]
  } | null
  /** Which declared skills this phase used (#1269); absent from a server that predates it. */
  skill_use?: PhaseSkillUseLike | null
}

/** One skill invoked through the Skill tool, and how many calls. */
export interface InvokedSkillLike {
  name: string
  count: number
}

/** A phase's skill use (API `PhaseSkillUseInfo`). */
export interface PhaseSkillUseLike {
  status: string
  /** The API always sends the lists; the schema marks them optional (they have defaults). */
  declared?: readonly string[]
  invoked?: readonly InvokedSkillLike[]
  summary_display: string
}

/** Skill use across the run (API `ExecutionSkillUseSummary`). */
export interface ExecutionSkillUseLike {
  declared?: readonly string[]
  invoked?: readonly InvokedSkillLike[]
  never_invoked?: readonly string[]
  not_known?: readonly string[]
  summary_display: string
}

const upper = (n: number) => formatTokens(n, { case: 'upper' })

export function phaseTokens(p: PhaseLike): number {
  return p.input_tokens + p.output_tokens + p.cache_creation_tokens + p.cache_read_tokens
}

/** "01", "02" ... */
export function phaseNumber(index: number): string {
  return String(index + 1).padStart(2, '0')
}

/** "60.2K read · 31.4K write · 1.8K out · 25 in". */
export function phaseTokenSplit(p: PhaseLike): string {
  return `${upper(p.cache_read_tokens)} read · ${upper(p.cache_creation_tokens)} write · ${upper(p.output_tokens)} out · ${upper(p.input_tokens)} in`
}

/** Seconds as the timeline writes them: "24.3s", "118.9s". */
export function phaseSeconds(seconds: number | null | undefined): string {
  if (typeof seconds !== 'number' || !Number.isFinite(seconds) || seconds < 0) return formatDurationPrecise(null)
  return `${(Math.round(seconds * 10) / 10).toFixed(1)}s`
}

/** Under a block: full "118.9s · 143.9K tokens · $0.0798", short "24.3s". */
export function phaseMeta(p: PhaseLike): { meta: string; metaShort: string; phone: string } {
  const dur = phaseSeconds(p.duration_seconds)
  const tokens = `${upper(phaseTokens(p))} tokens`
  return { meta: `${dur} · ${tokens} · ${formatCostPrecise(p.cost_usd)}`, metaShort: dur, phone: `${dur} · ${tokens}` }
}

/** "223.8s inside phases." Null when no phase has a duration yet. */
export function timelineCaption(phases: readonly PhaseLike[]): string | null {
  const known = phases.filter((p) => typeof p.duration_seconds === 'number')
  if (!known.length) return null
  const total = known.reduce((s, p) => s + (p.duration_seconds ?? 0), 0)
  return `${phaseSeconds(total)} inside phases.`
}

/** "claude" / "codex" from a model id or provider. */
export function agentOf(value: string | null | undefined): 'Claude' | 'Codex' | null {
  if (!value) return null
  const v = value.toLowerCase()
  if (v.includes('claude') || v.includes('anthropic') || ['haiku', 'sonnet', 'opus'].some((k) => v.includes(k))) return 'Claude'
  if (v.includes('codex') || v.includes('gpt') || v.includes('openai')) return 'Codex'
  return null
}

/**
 * The model chip: the observed model when there is one ("claude-haiku-4-5"),
 * otherwise what was asked for ("Claude · haiku requested"), otherwise the
 * API's display text.
 */
export function phaseModelChip(p: PhaseLike): string {
  if (p.model) return p.model
  const requested = p.requested_model ?? p.pinned_at_start?.requested_model ?? null
  if (requested) {
    const agent = agentOf(p.pinned_at_start?.provider) ?? agentOf(requested)
    return `${agent ? `${agent} · ` : ''}${requested} requested`
  }
  // Never a model that was not observed (feedback 58868cd8): the API's "unknown" reads "model not reported".
  return p.model_display && !/^unknown\b/i.test(p.model_display) ? p.model_display : 'model not reported'
}

/** Tools and skills for the phase's kit chips, from what was pinned at start. */
export function phaseKit(p: PhaseLike): { tools: readonly string[] | KitAbsence; skills: readonly SkillRefProps[] | KitAbsence } {
  const pins = p.pinned_at_start
  if (!pins) {
    const absent: KitAbsence = p.start_pins_status === 'not_recorded' || p.start_pins_status === undefined ? 'not-recorded' : 'not-reported'
    return { tools: absent, skills: absent }
  }
  return {
    tools: pins.allowed_tools && pins.allowed_tools.length ? pins.allowed_tools : 'default',
    skills: (pins.skills ?? []).map((s) => ({ name: s.name, source: s.source_url, ref: s.version, digest: s.resolved_sha })),
  }
}

/** A phase name as short as the cost rows need: "Discovery Phase" -> "Discovery", "Synthesis & Documentation" -> "Synthesis", "Deep Dive Analysis" -> "Deep Dive". */
export function shortPhaseName(name: string): string {
  const base = name.replace(/\s+phase$/i, '').split(/\s+(?:&|and)\s+/i)[0] ?? name
  return base.split(/\s+/).slice(0, 2).join(' ') || name
}

/** Usage Meter rows: "01 Discovery" with each phase's cost. */
export function costRowsByPhase(phases: readonly PhaseLike[]): CostRowInput[] {
  return phases.map((p, i) => ({ label: `${phaseNumber(i)} ${shortPhaseName(p.name)}`, value: toNumber(p.cost_usd), tone: 'accent' }))
}

/** The API's key for cost no model was observed for (React constants/models UNATTRIBUTED_MODEL_KEY). */
export const UNATTRIBUTED_MODEL_KEY = 'unattributed-model'

/**
 * "Cost by model": each phase's `cost_by_model` summed per model, largest
 * first (the React execution page's aggregateCostByModel). A running phase
 * has an empty map, so mid-run these add up to less than the total.
 */
export function costRowsByModel(phases: readonly PhaseLike[]): CostRowInput[] {
  const totals = new Map<string, number>()
  for (const p of phases)
    for (const [model, cost] of Object.entries(p.cost_by_model ?? {})) {
      const n = toNumber(cost)
      if (n !== null) totals.set(model, (totals.get(model) ?? 0) + n)
    }
  return [...totals]
    .sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))
    .map(([model, value]) => ({ label: model === UNATTRIBUTED_MODEL_KEY ? 'unknown model' : model, value }))
}

const WORDS = ['no', 'one', 'two', 'three', 'four', 'five', 'six', 'seven', 'eight', 'nine', 'ten']
const word = (n: number) => WORDS[n] ?? String(n)

/** Footnote when cost cannot be put against a model: "Model unknown: all three phases requested haiku, and the cost is not attributed to a model." */
export function usageNote(phases: readonly PhaseLike[]): string | undefined {
  const ran = phases.filter((p) => statusKind(p.status) !== 'pending')
  if (!ran.length || ran.some((p) => p.model)) return undefined
  const requested = [...new Set(ran.map((p) => p.requested_model).filter((m): m is string => !!m))]
  const subject = ran.length === 1 ? 'the phase' : `all ${word(ran.length)} phases`
  if (requested.length === 1) return `Model unknown: ${subject} requested ${requested[0]}, and the cost is not attributed to a model.`
  return `Model unknown: ${subject} ran without an observed model, and the cost is not attributed to a model.`
}

export interface InventorySummaryLike {
  complete: boolean
  coverage_state: string
  coverage_display: string
  revision: string | null
  platform_sessions: number | null
  native_transcripts: number | null
  invocations: number | null
  gaps: number | null
  remote_replication?: 'enabled' | 'disabled'
}

export interface InventoryLike {
  reconstruction_status: string
  later_evidence_pending: boolean
  summary: InventorySummaryLike
}

/** "f82315509573…b742d4d5" for a long revision. */
export function shortRevision(rev: string): string {
  return rev.length > 24 ? `${rev.slice(0, 12)}…${rev.slice(-8)}` : rev
}

/** Said only when the server sent no skill use at all (it predates #1269). */
export const SKILL_USE_NOT_REPORTED = 'Which skills an agent actually used is not reported by this server.'

const skillCall = (s: InvokedSkillLike, declared: ReadonlySet<string>) =>
  `${s.name}${s.count > 1 ? ` (${s.count} calls)` : ''}${declared.has(s.name) ? '' : ' (undeclared)'}`

/**
 * What the run's agents did with their skills, from the API's summary:
 * "Skills: 9 skills declared · 6 invoked · 3 use unknown · 1 undeclared
 * invoked. Invoked: architecture, claude-api (undeclared), ... Use unknown:
 * testing, security." The summary is the API's own words; the names are its
 * lists. Null when the server sent nothing.
 */
export function skillUseNote(use: ExecutionSkillUseLike | null | undefined): string | null {
  if (!use) return null
  const declared = new Set(use.declared ?? [])
  const invoked = use.invoked ?? []
  const notKnown = use.not_known ?? []
  const never = use.never_invoked ?? []
  const parts = [`Skills: ${use.summary_display}.`]
  if (invoked.length) parts.push(`Invoked: ${invoked.map((s) => skillCall(s, declared)).join(', ')}.`)
  if (notKnown.length) parts.push(`Use unknown: ${notKnown.join(', ')}.`)
  if (never.length) parts.push(`Never invoked: ${never.join(', ')}.`)
  return parts.join(' ')
}

/** A phase's skill-use line, the API's summary verbatim; null when it reported nothing to say. */
export function phaseSkillUseText(p: Pick<PhaseLike, 'skill_use'>): string | null {
  const use = p.skill_use
  if (!use || (!use.declared?.length && !use.invoked?.length)) return null
  return use.summary_display
}

/**
 * The Provenance strip. With no inventory (older server, or still loading),
 * the counts come from the phases themselves and coverage stays unproven.
 * The note reports skill use from the API's `skill_use`, and says it is not
 * reported only when the server sent none.
 */
export function provenanceFor(
  phases: readonly PhaseLike[],
  inventory: InventoryLike | null | undefined,
  skillUse?: ExecutionSkillUseLike | null,
): ProvenanceStripProps {
  const sessions = phases.filter((p) => statusKind(p.status) !== 'pending').length
  const pinsMissing = phases.some((p) => !p.pinned_at_start && p.start_pins_status !== 'recorded')
  const use = skillUseNote(skillUse) ?? SKILL_USE_NOT_REPORTED
  const note = pinsMissing
    ? `This run started before start config was pinned, so the tools and skills each phase had were not recorded. ${use}`
    : use
  if (!inventory) {
    return {
      counts: { platformSessions: sessions },
      warning: { lead: "Coverage can't be proven yet.", body: 'The sessions above are real; others may exist until the inventory is reconstructed.' },
      note,
      facts: [],
      actionLabel: null,
    }
  }
  const s = inventory.summary
  const facts: string[] = []
  if (s.revision) facts.push(`revision ${shortRevision(s.revision)}`)
  facts.push(`reconstruction ${inventory.reconstruction_status.replace(/_/g, ' ')}`)
  if (inventory.later_evidence_pending) facts.push('later evidence pending')
  if (s.remote_replication) facts.push(`remote replication ${s.remote_replication === 'enabled' ? 'on' : 'off'}`)
  return {
    counts: { platformSessions: s.platform_sessions, nativeTranscripts: s.native_transcripts, invocations: s.invocations, gaps: s.gaps },
    warning: s.complete ? null : { lead: "Coverage can't be proven for this harness.", body: s.coverage_display },
    note,
    facts,
    actionLabel: 'Load latest revision',
  }
}

export interface ExecutionIdentityLike {
  workflow_execution_id: string
  workflow_id: string
  workflow_name: string
  status: string
  started_at: string | null
  completed_at?: string | null
  repos?: readonly string[] | null
}

/** What "Copy run identity" puts on the clipboard: one fact per line, for a person or an agent. */
export function runIdentityText(e: ExecutionIdentityLike): string {
  const lines = [
    `execution: ${e.workflow_execution_id}`,
    `workflow: ${e.workflow_name} (${e.workflow_id})`,
    `status: ${e.status}`,
  ]
  if (e.started_at) lines.push(`started: ${e.started_at}`)
  if (e.completed_at) lines.push(`completed: ${e.completed_at}`)
  if (e.repos?.length) lines.push(`repos: ${e.repos.join(', ')}`)
  return lines.join('\n')
}

/** Cancel is offered only while a run can still be stopped. */
export function canCancel(status: string | null | undefined): boolean {
  const s = (status ?? '').toLowerCase()
  return s === 'running' || s === 'queued' || s === 'in_progress'
}

/** Activity events that should refresh an execution page or list: the API's real `event_type` names (data live/events.ts). */
const EXECUTION_EVENTS = new Set(['WorkflowExecutionStarted', 'WorkflowCompleted', 'WorkflowFailed', 'PhaseStarted', 'PhaseCompleted'])
export function isExecutionEvent(type: string): boolean {
  return EXECUTION_EVENTS.has(type)
}

/**
 * Header progress, counted the same way the phase list is drawn (every
 * planned phase, feedback 9a95d8f7): the API's display ("phase 2 of up to
 * 8", "3 of up to 10, failed") when present, else "1 of 3 phases".
 */
export function phaseProgressText(display: string | null | undefined, completed: number, total: number): string {
  if (!display) return `${completed} of ${total} ${total === 1 ? 'phase' : 'phases'}`
  return /\bphases?\b/i.test(display) ? display : `phases ${display}`
}

/**
 * Where a phase row leads (feedback 1f70d3ab): the whole row opens the
 * session the phase ran in. A phase with no session yet (planned, queued,
 * or started before the session was recorded) is not a link and says why.
 */
export type PhaseRowTarget = { kind: 'session'; path: string; label: string } | { kind: 'none'; reason: string }

export function phaseRowTarget(p: { name: string; status: string; session_id?: string | null }, planned = false): PhaseRowTarget {
  if (p.session_id) return { kind: 'session', path: `/sessions/${encodeURIComponent(p.session_id)}`, label: `Open the session for ${p.name}` }
  if (planned) return { kind: 'none', reason: 'This phase has not started yet, so it has no session to open.' }
  return statusKind(p.status) === 'running'
    ? { kind: 'none', reason: 'The session for this phase has not been recorded yet.' }
    : { kind: 'none', reason: 'No session was recorded for this phase.' }
}
