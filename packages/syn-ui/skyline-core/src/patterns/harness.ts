/**
 * Harnesses (Landing pillar 02, the "What is" phases card; later the app's
 * Execution, Workflow and Session pages): which agent harness runs a phase,
 * as a chip, and a workflow's phases laid out in one lane per harness.
 *
 * Ported from harness_chip() and harness_visual() in
 * design/reference/gen_landing4.py. Colours are token names only; the
 * renderer reads `var(token)`.
 */

/** Harnesses Syntropic137 runs today (`phases[].agent.provider` in a workflow). */
export type HarnessProvider = 'claude' | 'codex'

export const HARNESS_PROVIDERS = ['claude', 'codex'] as const satisfies readonly HarnessProvider[]

export interface HarnessLook {
  provider: HarnessProvider | 'other'
  /** Display name of the harness: "Claude Code", "Codex". */
  name: string
  /** Solid colour token, e.g. "--sky-harness-claude". */
  token: string
  /** Gradient token for marks set in the harness colour. */
  gradient: string
}

const LOOK: Record<HarnessProvider, HarnessLook> = {
  claude: { provider: 'claude', name: 'Claude Code', token: '--sky-harness-claude', gradient: '--sky-harness-claude-gradient' },
  codex: { provider: 'codex', name: 'Codex', token: '--sky-harness-codex', gradient: '--sky-harness-codex-gradient' },
}

/** "claude", "Claude Code", "anthropic" -> claude; "codex", "openai" -> codex; anything else is "other". */
export function harnessProvider(value: string | null | undefined): HarnessProvider | 'other' {
  const v = (value ?? '').trim().toLowerCase()
  if (v.startsWith('claude') || v === 'anthropic') return 'claude'
  if (v.startsWith('codex') || v === 'openai') return 'codex'
  return 'other'
}

/** Name and colour tokens of a harness; an unknown provider gets a muted dot and its own name. */
export function harnessLook(value: string | null | undefined): HarnessLook {
  const p = harnessProvider(value)
  if (p !== 'other') return LOOK[p]
  return { provider: 'other', name: (value ?? '').trim() || 'Unknown', token: '--ds-color-text-subtle', gradient: '--ds-color-text-subtle' }
}

export interface HarnessChipProps {
  /** Provider as a workflow names it: "claude" or "codex". */
  provider: string
  /** Chip text; defaults to the provider ("implement · claude", "claude-sonnet-5-5"). */
  label?: string
}

export interface HarnessPhase {
  name: string
  /** Provider of the phase: "claude" or "codex". */
  provider: string
  /** Relative width of the phase, e.g. its share of the run time (default 1). */
  span?: number
}

export interface HarnessLanesProps {
  phases: readonly HarnessPhase[]
  /** Accessible name of the lanes (default "Phases by harness"). */
  label?: string
}

export interface HarnessLaneCell {
  /** Phase name; "" in an empty cell. */
  name: string
  /** Flex weight (the phase's span). */
  span: number
  /** True where this lane runs the phase. */
  on: boolean
  /** Position of the phase in the workflow, 0 first. */
  index: number
}

export interface HarnessLane {
  provider: HarnessProvider | 'other'
  /** Lane label: the provider as written in the workflow ("claude"). */
  label: string
  token: string
  cells: HarnessLaneCell[]
  /** "claude runs plan and fix". */
  summary: string
}

const spanOf = (p: HarnessPhase) => (typeof p.span === 'number' && Number.isFinite(p.span) && p.span > 0 ? p.span : 1)

function list(names: string[]): string {
  if (names.length <= 1) return names[0] ?? 'nothing'
  return `${names.slice(0, -1).join(', ')} and ${names[names.length - 1]}`
}

/**
 * One lane per harness, in order of first use; every lane has one cell per
 * phase, so phase N lines up across lanes. A lane's cell is "on" where that
 * harness runs the phase and an empty, dashed slot elsewhere.
 */
export function harnessLanes(phases: readonly HarnessPhase[]): HarnessLane[] {
  const lanes = new Map<string, { label: string; look: HarnessLook }>()
  for (const p of phases) {
    const look = harnessLook(p.provider)
    const key = look.provider === 'other' ? `other:${look.name}` : look.provider
    if (!lanes.has(key)) lanes.set(key, { label: p.provider.trim().toLowerCase() || look.name, look })
  }
  return [...lanes.values()].map(({ label, look }) => {
    const cells = phases.map((p, index): HarnessLaneCell => {
      const mine = harnessLook(p.provider)
      const on = mine.provider === look.provider && (look.provider !== 'other' || mine.name === look.name)
      return { name: on ? p.name : '', span: spanOf(p), on, index }
    })
    return {
      provider: look.provider,
      label,
      token: look.token,
      cells,
      summary: `${label} runs ${list(cells.filter((c) => c.on).map((c) => c.name))}`,
    }
  })
}
