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

export interface EvalVariantLike {
  workflow_id: string
  workflow_version?: string | null
  models: readonly string[]
  avg_cost_usd?: string | null
  run_count: number
  last_run_at?: string | null
  last_verdict?: string | null
  stats?: { median_cost_usd?: string | null } | null
}

export interface EvalLike {
  eval_id: string
  name: string
  tags: readonly string[]
  last_verdict?: string | null
  last_run_at?: string | null
  run_count: number
  archived?: boolean
  starting_workflow_id?: string | null
  variants?: readonly EvalVariantLike[] | null
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
  /** Workflow per cell key: the variant whose latest run the readout shows. */
  workflows: Record<string, string>
  /** Common suite ("verifier-seed", "verifier-seed-v1 · v2"), when every eval shares one. */
  suite: string | null
}

export interface BoardOptions {
  /** Case sub line: "PR #1574 · 6646da2". */
  caseSub?: (caseId: string, evals: readonly EvalLike[]) => string | undefined
  evalHref?: (evalId: string) => string
}

/** One (case, workflow) result before it is placed on the board. */
interface BoardEntry {
  caseId: string
  workflow: string
  model: string
  agentTag: string | null
  verdict: Verdict
  costUsd: number | null
  runs: number
  at: number
  /** Stable-id evals (variants carry the verifiers) beat legacy one-per-verifier evals. */
  stable: boolean
  e: EvalLike
}

/**
 * Pivot evals into the Verdict Board: one cell per case x workflow.
 *
 * Two shapes feed it. A legacy eval is one (case, verifier) pair, tagged
 * `case:<id>` and `workflow:<id>` (or with a starting workflow). A stable-id
 * eval (`verifier-seed: <case>`) has only the `case:` tag and holds one
 * variant per verifier workflow, so it fills a whole row. Archived evals and
 * evals that never ran are left out. In one cell a stable-id eval beats a
 * legacy one, then the most recent run wins. Columns keep first-seen order
 * and never share a header: a model used by two workflows is named with its
 * workflow ("gpt-6.1-sol · sdlc-lean").
 */
export function buildEvalBoard(evals: readonly EvalLike[], options: BoardOptions = {}): EvalBoardModel {
  const board: EvalBoardModel = { cases: [], verifiers: [], cells: {}, evalIds: {}, workflows: {}, suite: null }
  const byCase = new Map<string, EvalLike[]>()
  const placed = new Map<string, BoardEntry>()
  const columns = new Map<string, BoardEntry>()
  const suites = new Set<string>()

  for (const e of evals) {
    const entries = boardEntries(e)
    if (!entries.length) continue
    suites.add(tagValue(e.tags, 'suite') ?? suiteOf(e.name) ?? '')
    addToCase(board.cases, byCase, entries[0]!.caseId, e)
    for (const entry of entries) {
      noteColumn(columns, entry)
      const key = cellKey(entry.caseId, entry.workflow)
      if (beats(entry, placed.get(key))) placed.set(key, entry)
    }
  }

  board.verifiers = verifierHeads([...columns.values()])
  for (const [key, entry] of placed) placeCell(board, key, entry, options)
  if (options.caseSub) for (const c of board.cases) c.sub = options.caseSub(c.id, byCase.get(c.id) ?? [])
  const only = suites.size === 1 ? [...suites][0] : ''
  board.suite = only || null
  return board
}

/** The board cells one eval contributes: none, one (legacy) or one per variant workflow (stable id). */
function boardEntries(e: EvalLike): BoardEntry[] {
  const caseId = tagValue(e.tags, 'case')
  if (!caseId || e.archived || e.run_count <= 0) return []
  const legacy = tagValue(e.tags, 'workflow') ?? e.starting_workflow_id ?? null
  if (legacy) return [legacyEntry(e, caseId, legacy)]
  return variantEntries(e, caseId)
}

function legacyEntry(e: EvalLike, caseId: string, wf: string): BoardEntry {
  const variant = e.variants?.find((v) => v.workflow_id === wf) ?? e.variants?.[0]
  return {
    caseId,
    workflow: wf,
    model: variant?.models[0] ?? wf,
    agentTag: tagValue(e.tags, 'agent'),
    verdict: normalizeVerdict(e.last_verdict),
    costUsd: toNum(variant?.avg_cost_usd),
    runs: e.run_count,
    at: time(e.last_run_at) ?? 0,
    stable: false,
    e,
  }
}

/** Variants of one workflow (several versions) collapse to the newest, with their runs summed. */
function variantEntries(e: EvalLike, caseId: string): BoardEntry[] {
  const out = new Map<string, BoardEntry>()
  for (const v of e.variants ?? []) {
    if (v.run_count <= 0) continue
    const entry = variantEntry(e, caseId, v)
    const prev = out.get(v.workflow_id)
    if (!prev) {
      out.set(v.workflow_id, entry)
      continue
    }
    const newer = entry.at >= prev.at ? entry : prev
    out.set(v.workflow_id, { ...newer, runs: prev.runs + entry.runs, model: newer.model || prev.model })
  }
  return [...out.values()]
}

function variantEntry(e: EvalLike, caseId: string, v: EvalVariantLike): BoardEntry {
  return {
    caseId,
    workflow: v.workflow_id,
    model: v.models[0] ?? '',
    agentTag: null,
    verdict: normalizeVerdict(v.last_verdict),
    costUsd: toNum(v.stats?.median_cost_usd) ?? toNum(v.avg_cost_usd),
    runs: v.run_count,
    at: time(v.last_run_at) ?? time(e.last_run_at) ?? 0,
    stable: true,
    e,
  }
}

function beats(next: BoardEntry, prev: BoardEntry | undefined): boolean {
  if (!prev) return true
  if (next.stable !== prev.stable) return next.stable
  return next.at >= prev.at
}

/** A column remembers the newest entry that names a model. */
function noteColumn(columns: Map<string, BoardEntry>, entry: BoardEntry): void {
  const prev = columns.get(entry.workflow)
  if (!prev || (entry.model && (!prev.model || entry.at > prev.at))) columns.set(entry.workflow, entry)
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

/** "eval-verify-pinned-sdlc-lean-v1" -> "sdlc-lean"; the pinned default -> "pinned". */
export function workflowLabel(workflowId: string): string {
  const core = workflowId.replace(/^eval-verify-pinned-?/, '').replace(/-?v\d+$/, '')
  return core || (workflowId.startsWith('eval-verify-pinned') ? 'pinned' : workflowId)
}

/** Column heads, made unique: a model shared by two workflows is suffixed with each workflow. */
function verifierHeads(columns: BoardEntry[]): Verifier[] {
  const heads = columns.map(verifierOf)
  const count = (pick: (v: Verifier) => string) => {
    const n = new Map<string, number>()
    for (const v of heads) n.set(pick(v), (n.get(pick(v)) ?? 0) + 1)
    return n
  }
  const models = count((v) => `${v.agent}|${v.model}`)
  for (const v of heads) {
    if ((models.get(`${v.agent}|${v.model}`) ?? 0) < 2) continue
    const label = workflowLabel(v.id)
    v.model = `${v.model} · ${label}`
    v.short = `${v.short} · ${label.split('-').pop()}`
  }
  const shorts = count((v) => v.short ?? '')
  for (const v of heads) if ((shorts.get(v.short ?? '') ?? 0) > 1) v.short = v.model
  return heads
}

function verifierOf(entry: BoardEntry): Verifier {
  const model = entry.model || entry.workflow
  const kind = entry.agentTag === 'claude' || entry.agentTag === 'codex' ? entry.agentTag : agentOfModel(entry.model || entry.workflow)
  return { id: entry.workflow, agent: AGENT_NAME[kind], agentKind: kind, model, short: shortModel(model), workflow: entry.workflow }
}

function placeCell(board: EvalBoardModel, key: string, entry: BoardEntry, options: BoardOptions): void {
  board.evalIds[key] = entry.e.eval_id
  board.workflows[key] = entry.workflow
  board.cells[key] = { verdict: entry.verdict, costUsd: entry.costUsd, runs: entry.runs, evalHref: options.evalHref?.(entry.e.eval_id) }
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

/**
 * The list's filter, run over evals already loaded: an exact tag
 * (`case:codex-cost-limit`) or any case-insensitive substring of the name or
 * a tag (`esp`). Empty matches everything.
 */
export function filterEvals<T extends EvalLike>(evals: readonly T[], query: string): T[] {
  const q = query.trim().toLowerCase()
  if (!q) return [...evals]
  return evals.filter((e) => e.name.toLowerCase().includes(q) || e.tags.some((t) => t.toLowerCase().includes(q)))
}

/** One page of rows (1-based), plus the page count (at least 1). */
export function pageOf<T>(rows: readonly T[], page: number, size: number): { rows: T[]; pageCount: number; from: number } {
  const pageCount = Math.max(1, Math.ceil(rows.length / size))
  const from = (page - 1) * size
  return { rows: rows.slice(from, from + size), pageCount, from: from + 1 }
}

/**
 * Sparkline verdicts from what the list already carries: the latest verdict
 * of each variant, oldest first. An eval with no variants falls back to its
 * own last verdict, and one that never ran has none.
 */
export function recentVerdicts(e: EvalLike): Verdict[] {
  if (e.run_count <= 0) return []
  const vs = [...(e.variants ?? [])].filter((v) => v.run_count > 0 && v.last_verdict !== undefined)
  if (!vs.length) return [normalizeVerdict(e.last_verdict)]
  vs.sort((a, b) => (time(a.last_run_at) ?? 0) - (time(b.last_run_at) ?? 0))
  return vs.map((v) => normalizeVerdict(v.last_verdict))
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

/** Words for a run or eval nobody has scored. Never "0/1", never a Fail. */
export const NOT_SCORED = 'Not scored yet'

/**
 * Compare row: "3/5" passed of scored runs and the bar fill 0..100. With
 * nothing scored it reads "Not scored yet" and has no fill, so an unscored
 * variant never looks like 0%.
 */
export function variantPassed(v: { run_count: number; pass_count: number; pass_rate?: number | null }): { fraction: string; fill: number | null } {
  if (v.pass_rate === null || v.pass_rate === undefined) return { fraction: NOT_SCORED, fill: null }
  const scored = v.pass_rate > 0 ? Math.round(v.pass_count / v.pass_rate) : null
  return { fraction: scored === null ? `${v.pass_count} passed` : `${v.pass_count}/${scored}`, fill: Math.round(v.pass_rate * 100) }
}

/** Verdict word for pills and cards: "Pass", "Fail", "Error", "Not scored yet". */
export function verdictWord(v: Verdict): string {
  if (v === 'unscored') return NOT_SCORED
  return v === 'error' ? 'Error' : v === 'pass' ? 'Pass' : 'Fail'
}

export type RunOutcomeKind = 'pass' | 'fail' | 'scorer-error' | 'run-failed' | 'unscored'

export interface RunOutcome {
  kind: RunOutcomeKind
  /** Pill text: "Pass", "Fail", "Scorer error", "Run failed", "Not scored yet". */
  word: string
  /** Verdict tone for the pill: a failed run is not a verdict, so it is neutral. */
  verdict: Verdict
}

const RUN_FAILED_STATUSES = new Set(['failed', 'cancelled', 'canceled', 'timed_out', 'error', 'errored', 'interrupted'])

/**
 * What a run's pill says. A run whose execution failed is "Run failed", not a
 * scorer fault, even when the scorer recorded ERROR for it; ERROR on a run
 * that completed is the scorer's fault.
 */
export function runOutcome(run: { verdict?: string | null; status?: string | null }): RunOutcome {
  const v = normalizeVerdict(run.verdict)
  const failedRun = RUN_FAILED_STATUSES.has((run.status ?? '').toLowerCase())
  if (failedRun && (v === 'error' || v === 'unscored')) return { kind: 'run-failed', word: 'Run failed', verdict: 'unscored' }
  if (v === 'error') return { kind: 'scorer-error', word: 'Scorer error', verdict: 'error' }
  if (v === 'unscored') return { kind: 'unscored', word: NOT_SCORED, verdict: 'unscored' }
  return { kind: v, word: verdictWord(v), verdict: v }
}

/** Facts read from the scorer's markdown excerpt (`eval_suite.py` format). */
export interface EvidenceFacts {
  /** "shared-esp-stream (defect)". */
  heading: string | null
  runStatus: string | null
  /** "blocked". */
  reviewVerdict: string | null
  /** What a pass needs: "blocked" or "certified". */
  reviewNeeds: string | null
  findings: number | null
  /** The file the scorer looked for, or "no (one of ...)". Backticks removed. */
  expectedFile: string | null
}

const unquote = (s: string) => s.replace(/`/g, '').trim()

type FactKey = 'runStatus' | 'review' | 'findings' | 'expectedFile'
const FACT_LABELS: Record<string, FactKey> = {
  'run status': 'runStatus',
  'review verdict': 'review',
  'blocking findings': 'findings',
  'expected file named': 'expectedFile',
}

/**
 * Parse an evidence excerpt shaped like
 * `## <case> (defect)` then `- run status: ...`, `- review verdict: ...`,
 * `- blocking findings: N`, `- expected file named: ...`. Returns null when
 * the text has none of those lines, so free text renders as it is.
 */
export function parseEvidence(text: string | null | undefined): EvidenceFacts | null {
  if (!text) return null
  const facts: EvidenceFacts = { heading: null, runStatus: null, reviewVerdict: null, reviewNeeds: null, findings: null, expectedFile: null }
  let found = false
  for (const line of text.split('\n')) {
    const h = line.match(/^#{1,6}\s+(.+)$/)
    if (h) facts.heading ??= h[1]!.trim()
    const m = line.match(/^\s*[-*]\s+([a-z ]+):\s*(.*)$/i)
    const key = m ? FACT_LABELS[m[1]!.trim().toLowerCase()] : undefined
    if (!m || !key) continue
    found = true
    applyFact(facts, key, m[2]!)
  }
  return found ? facts : null
}

function applyFact(facts: EvidenceFacts, key: FactKey, raw: string): void {
  if (key === 'review') {
    const r = raw.match(/^`?([^`(]+?)`?\s*(?:\(a pass needs `?([^`)]+)`?\))?\s*$/)
    facts.reviewVerdict = unquote(r?.[1] ?? raw)
    facts.reviewNeeds = r?.[2] ? unquote(r[2]) : null
  } else if (key === 'findings') {
    const n = Number.parseInt(raw, 10)
    facts.findings = Number.isFinite(n) ? n : null
  } else {
    facts[key] = unquote(raw)
  }
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

export * from './trend'
