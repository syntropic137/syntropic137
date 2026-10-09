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
  cost_usd: number
  model: string | null
  requested_model: string | null
  model_display?: string
  start_pins_status?: 'recorded' | 'not_recorded' | 'unavailable'
  pinned_at_start?: {
    provider: string
    requested_model?: string | null
    allowed_tools?: string[]
    skills?: { name: string; version: string; resolved_sha: string; source_url: string }[]
  } | null
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
  return p.model_display || 'model unknown'
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
  return phases.map((p, i) => ({ label: `${phaseNumber(i)} ${shortPhaseName(p.name)}`, value: p.cost_usd, tone: 'accent' }))
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

/**
 * The Provenance strip. With no inventory (older server, or still loading),
 * the counts come from the phases themselves and coverage stays unproven.
 */
export function provenanceFor(phases: readonly PhaseLike[], inventory: InventoryLike | null | undefined): ProvenanceStripProps {
  const sessions = phases.filter((p) => statusKind(p.status) !== 'pending').length
  const pinsMissing = phases.some((p) => !p.pinned_at_start && p.start_pins_status !== 'recorded')
  const note = pinsMissing
    ? 'This run started before start config was pinned, so the tools and skills each phase had were not recorded. Which skills an agent actually used is not reported yet either.'
    : 'Which skills an agent actually used is not reported yet.'
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
