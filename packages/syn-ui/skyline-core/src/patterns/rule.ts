/**
 * Rule Sentence (Triggers board): a trigger read as a sentence, one clause
 * per line: When, If, Then, Cap, Log.
 */

/** A run of text inside a clause. Plain strings are prose. */
export type RuleToken =
  | string
  | { code: string; tone?: 'neutral' | 'danger' }
  | { muted: string }
  | { link: string; href?: string }

export type RuleClauseKey = 'when' | 'if' | 'then' | 'cap' | 'log'

export interface RuleClause {
  key: RuleClauseKey
  /** One or more lines of tokens; extra If conditions start with a muted "and". */
  lines: RuleToken[][]
  /** Then: inputs as `key ← from`. */
  mapping?: { key: string; from: string }[]
  /** Cap: figures with a caption. */
  figures?: { value: string; label: string }[]
  /** Log: a sub line under the first line. */
  detail?: string
}

export const CLAUSE_LABEL: Record<RuleClauseKey, string> = { when: 'When', if: 'If', then: 'Then', cap: 'Cap', log: 'Log' }

export interface RuleCondition {
  field: string
  operator: string
  value?: string | null
}

/** Operator -> words, keyed by the lowercased operator. */
const OPERATOR_WORDS: Record<string, { words: string; takesValue: boolean }> = {
  eq: { words: 'equals', takesValue: true },
  equals: { words: 'equals', takesValue: true },
  '==': { words: 'equals', takesValue: true },
  neq: { words: 'does not equal', takesValue: true },
  ne: { words: 'does not equal', takesValue: true },
  not_equals: { words: 'does not equal', takesValue: true },
  '!=': { words: 'does not equal', takesValue: true },
  contains: { words: 'contains', takesValue: true },
  not_contains: { words: 'does not contain', takesValue: true },
  in: { words: 'is one of', takesValue: true },
  not_in: { words: 'is not one of', takesValue: true },
  matches: { words: 'matches', takesValue: true },
  regex: { words: 'matches', takesValue: true },
  starts_with: { words: 'starts with', takesValue: true },
  exists: { words: 'is set', takesValue: false },
  not_empty: { words: 'is not empty', takesValue: false },
  is_not_empty: { words: 'is not empty', takesValue: false },
  empty: { words: 'is empty', takesValue: false },
  is_empty: { words: 'is empty', takesValue: false },
}

/** Operator -> words. Unknown operators read as themselves. */
export function operatorWords(op: string): { words: string; takesValue: boolean } {
  const known = Object.hasOwn(OPERATOR_WORDS, op.toLowerCase()) ? OPERATOR_WORDS[op.toLowerCase()] : undefined
  return known ? { ...known } : { words: op.replace(/_/g, ' '), takesValue: true }
}

/** Values that read as an outcome to watch for get the coral code chip. */
const DANGER_VALUES = new Set(['failure', 'failed', 'error', 'timed_out', 'cancelled', 'action_required'])

export interface RuleInput {
  /** Event source, "GitHub". */
  source?: string
  /** "check_run.completed". */
  event: string
  repository?: string | null
  conditions?: readonly RuleCondition[] | null
  workflowName: string
  workflowHref?: string
  /** Input mapping: input name -> where it comes from. */
  inputs?: Record<string, unknown> | null
  caps?: { value: string; label: string }[]
  /** Log line: "Hasn't fired yet", "Fired 4 times, last 2h ago". */
  log?: string
  logDetail?: string
}

/** Build the clauses for a trigger. Clauses without content are left out (no If when there are no conditions). */
export function buildRuleClauses(r: RuleInput): RuleClause[] {
  const clauses: RuleClause[] = [whenClause(r)]
  const conds = r.conditions ?? []
  if (conds.length) clauses.push({ key: 'if', lines: conds.map(conditionLine) })
  clauses.push(thenClause(r))
  if (r.caps?.length) clauses.push({ key: 'cap', lines: [], figures: r.caps })
  if (r.log) clauses.push(logClause(r.log, r.logDetail))
  return clauses
}

function whenClause(r: RuleInput): RuleClause {
  const when: RuleToken[] = [`${r.source ?? 'GitHub'} sends `, { code: r.event }]
  if (r.repository) when.push(' on ', { code: r.repository })
  return { key: 'when', lines: [when] }
}

function hasValue(v: string | null | undefined): v is string {
  return v !== null && v !== undefined && v !== ''
}

function conditionLine(c: RuleCondition, i: number): RuleToken[] {
  const op = operatorWords(c.operator)
  const line: RuleToken[] = []
  if (i > 0) line.push({ muted: 'and' }, ' ')
  line.push({ code: c.field }, ` ${op.words}`)
  if (op.takesValue && hasValue(c.value)) {
    line.push(' ', { code: String(c.value), tone: DANGER_VALUES.has(String(c.value).toLowerCase()) ? 'danger' : 'neutral' })
  }
  return line
}

function inputPhrase(count: number): string {
  if (!count) return ''
  return count === 1 ? ' with this input' : ' with these inputs'
}

function thenClause(r: RuleInput): RuleClause {
  const mapping = Object.entries(r.inputs ?? {}).map(([key, from]) => ({ key, from: typeof from === 'string' ? from : JSON.stringify(from) }))
  const link: RuleToken = r.workflowHref ? { link: r.workflowName, href: r.workflowHref } : { link: r.workflowName }
  const then: RuleClause = { key: 'then', lines: [['Run ', link, inputPhrase(mapping.length)]] }
  if (mapping.length) then.mapping = mapping
  return then
}

function logClause(text: string, detail: string | undefined): RuleClause {
  const log: RuleClause = { key: 'log', lines: [[text]] }
  if (detail) log.detail = detail
  return log
}

/** The sentence as plain text, for an accessible summary or a copy. */
export function ruleText(clauses: readonly RuleClause[]): string {
  const tok = (t: RuleToken) => (typeof t === 'string' ? t : 'code' in t ? t.code : 'muted' in t ? t.muted : t.link)
  return clauses
    .map((c) => {
      const body = c.lines.map((l) => l.map(tok).join('')).join(' ')
      const figs = c.figures?.map((f) => `${f.value} ${f.label}`).join(', ') ?? ''
      return `${CLAUSE_LABEL[c.key]}: ${[body, figs].filter(Boolean).join(' ')}`.trim()
    })
    .join('. ')
}
