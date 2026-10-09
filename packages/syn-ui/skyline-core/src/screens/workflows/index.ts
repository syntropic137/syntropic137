/**
 * Workflows screens (boards: Workflows, PhoneWorkflows, Workflow,
 * PhoneWorkflow): list filters and sort, card labels, phase token shares,
 * the phase kit read from a phase definition, and a small prompt parser.
 */
import { formatCost } from '../../format/cost'
import type { PhaseKitProps, SkillRefProps } from '../../patterns/phaseKit'

// ---------------------------------------------------------------- list

export type WorkflowFilter = 'all' | 'research' | 'implementation' | 'review' | 'skills'
export type WorkflowSort = 'runs' | 'name'

export const WORKFLOW_FILTERS: readonly { value: WorkflowFilter; label: string }[] = [
  { value: 'all', label: 'All' },
  { value: 'research', label: 'Research' },
  { value: 'implementation', label: 'Implementation' },
  { value: 'review', label: 'Review' },
  { value: 'skills', label: 'Has skills' },
]

export function parseWorkflowFilter(v: string | null | undefined): WorkflowFilter {
  return WORKFLOW_FILTERS.some((f) => f.value === v) ? (v as WorkflowFilter) : 'all'
}

export function parseWorkflowSort(v: string | null | undefined): WorkflowSort {
  return v === 'name' ? 'name' : 'runs'
}

export interface WorkflowListItem {
  id: string
  name: string
  workflow_type: string
  phase_count: number
  runs_count: number
}

/** Card category shown with its icon; unknown types read as their own title-cased name. */
export type WorkflowCategory = 'Research' | 'Implementation' | 'Review' | 'Deployment' | 'Planning' | 'Custom'

export function workflowCategory(type: string | null | undefined): WorkflowCategory {
  const t = (type ?? '').toLowerCase()
  if (t === 'research') return 'Research'
  if (t === 'implementation') return 'Implementation'
  if (t === 'review') return 'Review'
  if (t === 'deployment') return 'Deployment'
  if (t === 'planning') return 'Planning'
  return 'Custom'
}

/** Lucide-style 16px paths per category (Workflows board). */
export const CATEGORY_ICON: Record<WorkflowCategory, string> = {
  Research: 'M11.25 7a4.25 4.25 0 1 1-8.5 0 4.25 4.25 0 0 1 8.5 0zM10.25 10.25L13.5 13.5',
  Implementation: 'M5.5 4.5L2 8l3.5 3.5M10.5 4.5L14 8l-3.5 3.5',
  Review: 'M13.75 8A5.75 5.75 0 1 1 2.25 8a5.75 5.75 0 0 1 11.5 0zM5.5 8.25l1.75 1.75 3.25-3.75',
  Deployment: 'M8 12.5v-9M4.5 7L8 3.5 11.5 7M3 13.25h10',
  Planning: 'M3 4h10M3 8h10M3 12h6',
  Custom: 'M8 2.5l5 2.75v5.5L8 13.5l-5-2.75v-5.5z',
}

/**
 * Filter, search and sort the list. `skillsOf` answers which skills a
 * workflow declares (undefined while not yet known, which never matches
 * "Has skills").
 */
export function filterWorkflows<T extends WorkflowListItem>(
  rows: readonly T[],
  opts: { filter: WorkflowFilter; sort: WorkflowSort; search?: string; skillsOf?: (id: string) => readonly string[] | undefined },
): T[] {
  const q = (opts.search ?? '').trim().toLowerCase()
  const out = rows.filter((r) => {
    if (q && !r.name.toLowerCase().includes(q) && !r.id.toLowerCase().includes(q)) return false
    if (opts.filter === 'all') return true
    if (opts.filter === 'skills') return (opts.skillsOf?.(r.id)?.length ?? 0) > 0
    return r.workflow_type.toLowerCase() === opts.filter
  })
  return out.sort((a, b) =>
    opts.sort === 'name'
      ? a.name.localeCompare(b.name) || a.id.localeCompare(b.id)
      : b.runs_count - a.runs_count || a.name.localeCompare(b.name) || a.id.localeCompare(b.id),
  )
}

export const runsLabel = (n: number): string => (n <= 0 ? 'never run' : n === 1 ? '1 run' : `${n} runs`)
export const phasesLabel = (n: number): string => (n === 1 ? '1 phase' : `${n} phases`)

/** Run bar on a card: share of the most-run workflow in view, 0-100. */
export function runSharePercent(runs: number, most: number): number {
  if (!most || most <= 0 || runs <= 0) return 0
  return Math.min(100, Math.round((runs / most) * 100))
}

/** "Showing 12 of 27 workflows with skills". */
export function workflowsSummary(shown: number, matched: number, filter: WorkflowFilter): string {
  const what = filter === 'all' ? 'workflows' : filter === 'skills' ? 'workflows with skills' : `${filter} workflows`
  return `Showing ${shown} of ${matched} ${what}`
}

/** Unique skill names declared across a workflow's phases, in first-seen order. */
export function workflowSkillNames(phases: readonly { skills?: readonly SkillLike[] | null }[]): string[] {
  const seen = new Set<string>()
  for (const p of phases) for (const s of p.skills ?? []) seen.add(skillName(s))
  return [...seen]
}

/** Unique skills declared across a workflow's phases (first-seen by name), as Skill Ref props for linked chips. */
export function workflowSkillRefs(phases: readonly { skills?: readonly SkillLike[] | null }[]): SkillRefProps[] {
  const seen = new Map<string, SkillRefProps>()
  for (const p of phases) for (const s of p.skills ?? []) if (!seen.has(skillName(s))) seen.set(skillName(s), skillRef(s))
  return [...seen.values()]
}

// ---------------------------------------------------------------- detail

export interface SkillLike {
  name?: string | null
  source_url?: string | null
  version?: string | null
  raw?: string | null
}

export function skillName(s: SkillLike): string {
  if (s.name) return s.name
  const src = s.source_url ?? s.raw ?? ''
  const tail = src.replace(/[@#].*$/, '').split('/').filter(Boolean).pop()
  return tail || 'skill'
}

export function skillRef(s: SkillLike): SkillRefProps {
  return { name: skillName(s), source: s.source_url ?? s.raw ?? skillName(s), ref: s.version ?? null }
}

export interface PhaseDefinitionLike {
  phase_id: string
  name: string
  agent_type?: string | null
  provider?: string | null
  model?: string | null
  model_display?: string | null
  allowed_tools?: readonly string[] | null
  skills?: readonly SkillLike[] | null
  timeout_seconds?: number | null
}

export function agentOf(p: Pick<PhaseDefinitionLike, 'provider' | 'agent_type'>): { agent: string; agentKind: 'claude' | 'codex' | 'other' } {
  const raw = (p.provider || p.agent_type || '').toLowerCase()
  if (raw.includes('claude') || raw.includes('anthropic')) return { agent: 'Claude', agentKind: 'claude' }
  if (raw.includes('codex') || raw.includes('openai')) return { agent: 'Codex', agentKind: 'codex' }
  return { agent: raw ? raw[0]!.toUpperCase() + raw.slice(1) : 'Agent', agentKind: 'other' }
}

/** "What this phase gets", as declared on the workflow. */
export function phaseKitOf(p: PhaseDefinitionLike): PhaseKitProps {
  const tools = p.allowed_tools?.length ? [...p.allowed_tools] : 'default'
  const skills = p.skills?.length ? p.skills.map(skillRef) : 'none'
  const resolution = p.model_display || p.model || undefined
  return {
    model: { ...agentOf(p), ...(resolution ? { resolution } : {}) },
    tools,
    toolsNote: tools === 'default' ? 'no restriction declared' : undefined,
    skills,
  }
}

/** Short model for chips: the concrete id after the last arrow, "default" when none. */
export function phaseModelChip(p: Pick<PhaseDefinitionLike, 'model' | 'model_display'>): string {
  const d = p.model_display || p.model
  if (!d) return 'default model'
  const parts = d.split('→').map((s) => s.trim())
  return parts[parts.length - 1] || d
}

export function formatTimeout(seconds: number | null | undefined): string {
  return seconds && seconds > 0 ? `${seconds}s` : '—'
}

export interface PhaseUsageInput {
  phase_id: string
  total_tokens: number
  cost_usd: number | string
}

export interface PhaseShare {
  tokens: number
  cost: number
  /** 0-1 of the workflow's tokens across the given runs. */
  share: number
}

/** Sum each phase's tokens and cost over the given runs; shares add up to 1 (or all 0 without usage). */
export function phaseShares(phaseIds: readonly string[], runs: readonly { phase_results: readonly PhaseUsageInput[] }[]): Record<string, PhaseShare> {
  const out: Record<string, PhaseShare> = {}
  for (const id of phaseIds) out[id] = { tokens: 0, cost: 0, share: 0 }
  for (const r of runs)
    for (const p of r.phase_results) {
      const row = out[p.phase_id]
      if (!row) continue
      row.tokens += p.total_tokens || 0
      row.cost += Number(p.cost_usd) || 0
    }
  const total = Object.values(out).reduce((n, r) => n + r.tokens, 0)
  if (total > 0) for (const r of Object.values(out)) r.share = r.tokens / total
  return out
}

export interface PhaseMetricsInput extends PhaseUsageInput {
  /** True while a session of the phase is still running: the cost is a lower bound. */
  cost_in_progress?: boolean | null
}

export interface PhaseUsage extends PhaseShare {
  /** The cost is a lower bound (render "≥"). */
  partial: boolean
}

/**
 * Per-phase tokens and cost from GET /metrics?workflow_id= (`phases`, one row
 * per phase over every run of the workflow, as the React page charts them).
 * Shares are of the defined phases' tokens.
 */
export function phaseUsage(phaseIds: readonly string[], phases: readonly PhaseMetricsInput[]): Record<string, PhaseUsage> {
  const shares = phaseShares(phaseIds, [{ phase_results: phases }])
  const out: Record<string, PhaseUsage> = {}
  for (const id of phaseIds) out[id] = { ...shares[id]!, partial: phases.some((p) => p.phase_id === id && p.cost_in_progress === true) }
  return out
}

/** "≥$267.01" while the phase's cost is still accruing, else "$267.01". */
export function phaseCostLabel(u: PhaseUsage): string {
  return `${u.partial ? '≥' : ''}${formatCost(u.cost)}`
}

/** Which third of a 3-slab icon to light for phase `index` of `count`: 0 top, 1 middle, 2 bottom. */
export function phaseSlab(index: number, count: number): 0 | 1 | 2 {
  if (count <= 1) return 0
  const t = index / (count - 1)
  return t < 1 / 3 ? 0 : t < 2 / 3 ? 1 : 2
}

// ---------------------------------------------------------------- prompt

export type PromptBlock =
  | { kind: 'heading'; text: string }
  | { kind: 'paragraph'; text: string }
  | { kind: 'list'; items: string[] }
  | { kind: 'argument'; name: string }

/**
 * Split a phase prompt template into display blocks: "#" headings, "-"/"*"
 * lists, a line that is only `$ARGUMENTS` or `{{task}}` becomes the
 * argument slot, everything else paragraphs.
 */
export function parsePrompt(template: string | null | undefined): PromptBlock[] {
  const acc = new PromptAccumulator()
  for (const raw of (template ?? '').split('\n')) acc.line(raw.trim())
  acc.flush()
  return acc.blocks
}

const PROMPT_ARGUMENT = /^(\$[A-Z_]+|\{\{\s*[a-z_]+\s*\}\})$/
const PROMPT_HEADING = /^#{1,6}\s+(.*)$/
const PROMPT_LIST_ITEM = /^[-*]\s+(.*)$/

/** parsePrompt's line state: the open paragraph and the open list. */
class PromptAccumulator {
  readonly blocks: PromptBlock[] = []
  private para: string[] = []
  private list: string[] | null = null

  line(line: string): void {
    if (!line) {
      this.flush()
      return
    }
    const arg = PROMPT_ARGUMENT.exec(line)
    if (arg) {
      this.block({ kind: 'argument', name: arg[1]!.replace(/[{}\s]/g, '') })
      return
    }
    const h = PROMPT_HEADING.exec(line)
    if (h) {
      this.block({ kind: 'heading', text: h[1]! })
      return
    }
    const li = PROMPT_LIST_ITEM.exec(line)
    if (li) this.listItem(li[1]!)
    else this.paragraphLine(line)
  }

  flush(): void {
    this.flushParagraph()
    this.flushList()
  }

  private block(b: PromptBlock): void {
    this.flush()
    this.blocks.push(b)
  }

  private flushParagraph(): void {
    if (this.para.length) this.blocks.push({ kind: 'paragraph', text: this.para.join(' ') })
    this.para = []
  }

  private flushList(): void {
    if (this.list) this.blocks.push({ kind: 'list', items: this.list })
    this.list = null
  }

  private listItem(text: string): void {
    this.flushParagraph()
    ;(this.list ??= []).push(text)
  }

  private paragraphLine(line: string): void {
    this.flushList()
    this.para.push(line)
  }
}

export * from './trend'

export * from './detail'
export * from './performance'
