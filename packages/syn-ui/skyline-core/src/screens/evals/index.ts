/**
 * Evals screens (Evals, Eval, PhoneEvals, PhoneEval boards): pure helpers
 * that pivot the eval list into the Verdict Board, find an eval's siblings
 * (same case, other verifiers) and lay out the Runs over time lanes.
 *
 * Inputs are structural so this module stays free of the data package: the
 * API's EvalResponse and EvalRunResponse satisfy them.
 */
import { formatCost } from '../../format/cost'
import { normalizeVerdict, type Verdict, type VerdictCase, type VerdictCell, type VerdictMatrix, type Verifier, cellKey } from '../../patterns/verdict'

export interface EvalLike {
  eval_id: string
  name: string
  tags: readonly string[]
  last_verdict?: string | null
  last_run_at?: string | null
  run_count: number
  starting_workflow_id?: string | null
  variants?: readonly { workflow_id: string; models: readonly string[]; avg_cost_usd?: string | null; run_count: number }[] | null
}

export interface EvalRunLike {
  execution_id: string
  started_at?: string | null
  workflow_id?: string | null
  workflow_version?: string | null
  models?: readonly { phase_id?: string | null; model: string }[] | null
  verdict?: string | null
}

/** Value of the first `prefix:` tag, e.g. tagValue(tags, 'case') -> "shared-esp-stream". */
export function tagValue(tags: readonly string[], prefix: string): string | null {
  const p = `${prefix}:`
  const t = tags.find((x) => x.startsWith(p))
  return t ? t.slice(p.length) : null
}

/** "claude-opus-5-5" -> claude, "gpt-5.6-sol" -> codex. */
export function agentOfModel(model: string | null | undefined): 'claude' | 'codex' | 'other' {
  const m = (model ?? '').toLowerCase()
  if (m.startsWith('claude') || m.includes('opus') || m.includes('sonnet') || m.includes('haiku')) return 'claude'
  if (m.startsWith('gpt') || m.includes('codex') || /^o\d/.test(m)) return 'codex'
  return 'other'
}

const AGENT_NAME = { claude: 'Claude', codex: 'Codex', other: 'Agent' } as const

/** "claude-opus-5-5" -> "opus", "gpt-5.6-terra" -> "terra". */
export function shortModel(model: string): string {
  const known = model.match(/(opus|sonnet|haiku)/)
  if (known) return known[1]!
  const parts = model.split('-').filter(Boolean)
  return parts[parts.length - 1] ?? model
}

const toNum = (v: string | number | null | undefined): number | null => {
  if (v === null || v === undefined || v === '') return null
  const n = typeof v === 'number' ? v : Number(v)
  return Number.isFinite(n) ? n : null
}

const time = (v: string | null | undefined) => {
  const t = v ? Date.parse(v) : NaN
  return Number.isFinite(t) ? t : null
}

export interface EvalBoardModel {
  cases: VerdictCase[]
  verifiers: Verifier[]
  cells: VerdictMatrix
  /** Eval id per cell key, for the readout's links and detail fetch. */
  evalIds: Record<string, string>
  /** Common suite tag prefix ("verifier-seed-v1 · v2"), when every eval shares one. */
  suite: string | null
}

export interface BoardOptions {
  /** Case sub line: "PR #1574 · 6646da2". */
  caseSub?: (caseId: string, evals: readonly EvalLike[]) => string | undefined
  evalHref?: (evalId: string) => string
}

/**
 * Pivot evals tagged `case:<id>` and `workflow:<id>` into the Verdict
 * Board. Evals missing either tag are left out. When two evals land in one
 * cell the most recently run one wins. Verifiers keep first-seen order of
 * their earliest run so the column order is stable.
 */
export function buildEvalBoard(evals: readonly EvalLike[], options: BoardOptions = {}): EvalBoardModel {
  const board: EvalBoardModel = { cases: [], verifiers: [], cells: {}, evalIds: {}, suite: null }
  const winner: Record<string, number> = {}
  const byCase = new Map<string, EvalLike[]>()
  const suites = new Set<string>()

  for (const e of evals) {
    const caseId = tagValue(e.tags, 'case')
    const wf = evalWorkflow(e)
    if (!caseId || !wf) continue
    suites.add(suiteOf(e.name) ?? '')
    addToCase(board.cases, byCase, caseId, e)
    const variant = evalVariant(e, wf)
    addVerifier(board.verifiers, e, wf, variant?.models[0] ?? wf)
    placeCell(board, winner, cellKey(caseId, wf), e, variant, options)
  }

  if (options.caseSub) for (const c of board.cases) c.sub = options.caseSub(c.id, byCase.get(c.id) ?? [])
  const only = suites.size === 1 ? [...suites][0] : ''
  board.suite = only || null
  return board
}

type EvalVariant = NonNullable<EvalLike['variants']>[number]

function evalWorkflow(e: EvalLike): string | null {
  return tagValue(e.tags, 'workflow') ?? e.starting_workflow_id ?? null
}

function evalVariant(e: EvalLike, wf: string): EvalVariant | undefined {
  return e.variants?.find((v) => v.workflow_id === wf) ?? e.variants?.[0]
}

function addToCase(cases: VerdictCase[], byCase: Map<string, EvalLike[]>, caseId: string, e: EvalLike): void {
  let list = byCase.get(caseId)
  if (!list) {
    list = []
    byCase.set(caseId, list)
    cases.push({ id: caseId, name: caseId })
  }
  list.push(e)
}

function addVerifier(verifiers: Verifier[], e: EvalLike, wf: string, model: string): void {
  if (verifiers.some((v) => v.id === wf)) return
  const tagged = tagValue(e.tags, 'agent')
  const kind = tagged === 'claude' || tagged === 'codex' ? tagged : agentOfModel(model)
  verifiers.push({ id: wf, agent: AGENT_NAME[kind], agentKind: kind, model, short: shortModel(model), workflow: wf })
}

/** The most recently run eval wins a cell. */
function placeCell(board: EvalBoardModel, winner: Record<string, number>, key: string, e: EvalLike, variant: EvalVariant | undefined, options: BoardOptions): void {
  const t = time(e.last_run_at) ?? 0
  if (winner[key] !== undefined && winner[key]! > t) return
  winner[key] = t
  board.evalIds[key] = e.eval_id
  board.cells[key] = {
    verdict: e.run_count > 0 ? normalizeVerdict(e.last_verdict) : 'unscored',
    costUsd: toNum(variant?.avg_cost_usd),
    runs: e.run_count,
    evalHref: options.evalHref?.(e.eval_id),
  }
}

/** "verifier-seed-v1 v2: shared-esp-stream" -> "verifier-seed-v1 · v2". */
export function suiteOf(name: string): string | null {
  const m = name.match(/^(\S+)\s+(v\d+)\s*:/)
  return m ? `${m[1]} · ${m[2]}` : null
}

/** Newest run first; evals never run sink to the end. */
export function sortEvalsByLastRun<T extends EvalLike>(evals: readonly T[]): T[] {
  return [...evals].sort((a, b) => (time(b.last_run_at) ?? -Infinity) - (time(a.last_run_at) ?? -Infinity))
}

/** Other evals of the same case (tag `case:<id>`), current one included, in verifier order. */
export function sameCaseSiblings<T extends EvalLike>(current: EvalLike, all: readonly T[]): T[] {
  const caseId = tagValue(current.tags, 'case')
  if (!caseId) return []
  return all.filter((e) => tagValue(e.tags, 'case') === caseId)
}

export interface TimelinePoint {
  executionId: string
  verdict: Verdict
  /** 0..100 across the lane. */
  x: number
  startedAt: string | null
}

export interface TimelineLane {
  key: string
  /** "eval-verify-pinned-v1 · claude-opus-5-5". */
  label: string
  points: TimelinePoint[]
}

export interface Timeline {
  lanes: TimelineLane[]
  /** Axis ticks: ISO start and end (equal for a single run). */
  start: string | null
  end: string | null
}

/** Unique model names of a run, in phase order: "claude-opus-5-5". */
export function runModels(run: EvalRunLike): string[] {
  return [...new Set((run.models ?? []).map((m) => m.model))]
}

/**
 * Runs over time: one lane per variant (workflow, version, model set), a
 * dot per run placed by start time. A single run, or runs at one instant,
 * sit in the middle.
 */
export function runsTimeline(runs: readonly EvalRunLike[]): Timeline {
  const { min, max } = timeBounds(runs)
  const place = timelinePlacer(min, max)
  const lanes = new Map<string, TimelineLane>()
  for (const r of runs) {
    const models = runModels(r)
    const lane = timelineLane(lanes, r, models)
    lane.points.push({ executionId: r.execution_id, verdict: normalizeVerdict(r.verdict), x: place(time(r.started_at)), startedAt: r.started_at ?? null })
  }
  for (const lane of lanes.values()) lane.points.sort((a, b) => a.x - b.x)
  return {
    lanes: [...lanes.values()],
    start: min === null ? null : new Date(min).toISOString(),
    end: max === null ? null : new Date(max).toISOString(),
  }
}

function timeBounds(runs: readonly EvalRunLike[]): { min: number | null; max: number | null } {
  const times = runs.map((r) => time(r.started_at)).filter((t): t is number => t !== null)
  if (!times.length) return { min: null, max: null }
  return { min: Math.min(...times), max: Math.max(...times) }
}

/** x on 4..96, rounded to 0.1; 50 when there is no span to spread over. */
function timelinePlacer(min: number | null, max: number | null): (t: number | null) => number {
  const span = min !== null && max !== null ? max - min : 0
  return (t) => {
    const x = t === null || min === null || span === 0 ? 50 : 4 + ((t - min) / span) * 92
    return Math.round(x * 10) / 10
  }
}

function timelineLane(lanes: Map<string, TimelineLane>, r: EvalRunLike, models: string[]): TimelineLane {
  const wf = r.workflow_id ?? 'unknown workflow'
  const key = `${wf}@${r.workflow_version ?? ''}|${models.join(',')}`
  let lane = lanes.get(key)
  if (!lane) {
    const version = r.workflow_version && r.workflow_version !== 'v1' ? ` ${r.workflow_version}` : ''
    lane = { key, label: [wf + version, models.join(', ')].filter(Boolean).join(' · '), points: [] }
    lanes.set(key, lane)
  }
  return lane
}

/** Compare row: "3/5" and the bar fill 0..100 (null when nothing is scored). */
export function variantPassed(v: { run_count: number; pass_count: number; pass_rate?: number | null }): { fraction: string; fill: number | null } {
  return { fraction: `${v.pass_count}/${v.run_count}`, fill: v.pass_rate === null || v.pass_rate === undefined ? null : Math.round(v.pass_rate * 100) }
}

/** Header figure: average cost over variants weighted by their run count. */
export function averageEvalCost(variants: readonly { run_count: number; avg_cost_usd?: string | null }[] | null | undefined): string {
  let sum = 0
  let n = 0
  for (const v of variants ?? []) {
    const c = toNum(v.avg_cost_usd)
    if (c === null || v.run_count <= 0) continue
    sum += c * v.run_count
    n += v.run_count
  }
  return n === 0 ? formatCost(null) : formatCost(sum / n)
}

/** Default scorer evidence when the run has none. */
export function evidenceFallback(verdict: Verdict): string {
  switch (verdict) {
    case 'unscored':
      return 'Not scored yet. Evidence appears here once the suite scorer has judged the run.'
    case 'error':
      return 'The scorer could not read a verdict from the run.'
    default:
      return 'The scorer left no evidence for this run.'
  }
}

/** Board readout cell enriched with the latest run of the selected eval. */
export function withLatestRun(cell: VerdictCell | undefined, run: (EvalRunLike & { evidence_excerpt?: string | null; duration_seconds?: number | null; total_cost_usd?: string | null }) | undefined, extra: { date?: string; runHref?: string } = {}): VerdictCell | undefined {
  if (!cell || !run) return cell
  const verdict = normalizeVerdict(run.verdict)
  return {
    ...cell,
    verdict,
    costUsd: toNum(run.total_cost_usd) ?? cell.costUsd,
    durationMs: typeof run.duration_seconds === 'number' ? run.duration_seconds * 1000 : cell.durationMs,
    evidence: run.evidence_excerpt ?? evidenceFallback(verdict),
    ...extra,
  }
}
