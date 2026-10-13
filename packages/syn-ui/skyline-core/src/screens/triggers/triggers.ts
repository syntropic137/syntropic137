/**
 * Triggers screen helpers: titles, grouping by repo, filtering, and turning a
 * trigger's raw conditions / input mapping / config into Rule Sentence input.
 */
import type { RuleCondition, RuleInput } from '../../patterns/rule'

export interface TriggerLike {
  trigger_id: string
  name: string
  event: string
  repository: string
  workflow_id: string
  workflow_name?: string | null
  status: string
  fire_count: number
}

/** "check_run.completed → Self-Heal PR", the React app's title rule. */
export function triggerTitle(t: Pick<TriggerLike, 'event' | 'workflow_name' | 'name'>): string {
  return t.workflow_name ? `${t.event} → ${t.workflow_name}` : t.name
}

export interface TriggerFilter {
  q?: string
  status?: string
}

export function filterTriggers<T extends TriggerLike>(list: readonly T[], f: TriggerFilter): T[] {
  const q = f.q?.trim().toLowerCase()
  return list.filter(
    (t) =>
      (!f.status || f.status === 'all' || t.status === f.status) &&
      (!q || [t.name, t.event, t.repository, t.workflow_name ?? '', t.workflow_id, t.trigger_id].some((s) => s.toLowerCase().includes(q))),
  )
}

export interface TriggerGroup<T> {
  repo: string
  rules: T[]
}

/** Group by repository, repos sorted by name; rules keep their order. */
export function groupTriggersByRepo<T extends TriggerLike>(list: readonly T[]): TriggerGroup<T>[] {
  const map = new Map<string, T[]>()
  for (const t of list) {
    const key = t.repository || 'No repository'
    const arr = map.get(key) ?? []
    arr.push(t)
    map.set(key, arr)
  }
  return [...map.entries()].sort(([a], [b]) => a.localeCompare(b)).map(([repo, rules]) => ({ repo, rules }))
}

/** Header sentence: "6 rules across 2 repos, all active." */
export function triggerSummary(list: readonly TriggerLike[]): string {
  if (!list.length) return 'No rules yet.'
  const repos = new Set(list.map((t) => t.repository)).size
  const paused = list.filter((t) => t.status === 'paused').length
  const head = `${list.length} ${list.length === 1 ? 'rule' : 'rules'} across ${repos} ${repos === 1 ? 'repo' : 'repos'}`
  const tail = paused === 0 ? (list.length === 1 ? 'active' : 'all active') : paused === list.length ? (list.length === 1 ? 'paused' : 'all paused') : `${paused} paused`
  return `${head}, ${tail}.`
}

/**
 * Conditions arrive either as a list of `{field, operator, value}` or as a
 * plain `{field: value}` object (equality). Anything else is skipped.
 */
export function normalizeConditions(raw: unknown): RuleCondition[] {
  if (Array.isArray(raw)) return conditionsFromList(raw)
  if (!raw || typeof raw !== 'object') return []
  const o = raw as Record<string, unknown>
  if (Array.isArray(o.conditions)) return conditionsFromList(o.conditions)
  return Object.entries(o).map(([field, v]) => ({ field, operator: 'eq', value: typeof v === 'string' ? v : JSON.stringify(v) }))
}

function conditionsFromList(items: unknown[]): RuleCondition[] {
  return items.flatMap((c) => {
    const condition = conditionFromItem(c)
    return condition ? [condition] : []
  })
}

function conditionFromItem(c: unknown): RuleCondition | undefined {
  if (!c || typeof c !== 'object') return undefined
  const o = c as Record<string, unknown>
  if (typeof o.field !== 'string') return undefined
  return { field: o.field, operator: typeof o.operator === 'string' ? o.operator : 'eq', value: conditionValue(o.value) }
}

function conditionValue(v: unknown): string | null {
  if (v === undefined || v === null) return null
  return typeof v === 'string' ? v : JSON.stringify(v)
}

const CAP_KEYS: { keys: string[]; label: string; unit?: string }[] = [
  { keys: ['max_attempts'], label: 'max attempts' },
  { keys: ['daily_limit', 'max_fires_per_day'], label: 'runs per day' },
  { keys: ['cooldown_seconds'], label: 'cooldown', unit: 's' },
  { keys: ['debounce_seconds'], label: 'debounce', unit: 's' },
]

/** Config -> Cap figures, in the board's order; missing keys are left out. */
export function triggerCaps(config: Record<string, unknown> | null | undefined): { value: string; label: string }[] {
  if (!config) return []
  return CAP_KEYS.flatMap(({ keys, label, unit }) => {
    const k = keys.find((key) => config[key] !== undefined && config[key] !== null)
    if (!k) return []
    return [{ value: `${String(config[k])}${unit ?? ''}`, label }]
  })
}

export interface TriggerDetailLike extends TriggerLike {
  conditions: Record<string, unknown> | unknown[] | null
  input_mapping: Record<string, unknown> | null
  config: Record<string, unknown> | null
}

/** Everything buildRuleClauses() needs, except the log line the page computes from history. */
export function triggerRuleInput(t: TriggerDetailLike, log?: { text: string; detail?: string }): RuleInput {
  const input: RuleInput = {
    source: 'GitHub',
    event: t.event,
    repository: t.repository || null,
    conditions: normalizeConditions(t.conditions),
    workflowName: t.workflow_name || t.workflow_id,
    workflowHref: `/workflows/${t.workflow_id}`,
    inputs: t.input_mapping,
    caps: triggerCaps(t.config),
  }
  if (log) {
    input.log = log.text
    if (log.detail) input.logDetail = log.detail
  }
  return input
}

/** The Log clause headline: "Hasn't fired yet" / "Fired 42 times". */
export function triggerLogLine(fireCount: number, historyCount: number): { text: string; detail: string } {
  const n = Math.max(fireCount, historyCount)
  if (n === 0) return { text: "Hasn't fired yet", detail: 'Each firing will list the event, the execution it started and the outcome.' }
  return { text: `Fired ${n} ${n === 1 ? 'time' : 'times'}`, detail: historyCount ? `Latest ${historyCount} below.` : 'No firing history recorded.' }
}
