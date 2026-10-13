/**
 * Day Readout (Main, PhoneOverview, CompPatterns): the pointed or stepped
 * Skyline day, formatted once for both the desktop dock and the phone card.
 */
import { formatCost } from '../format/cost'
import { formatTokens, TOKEN_SERIES } from '../format/tokens'
import { MONTHS, WEEKDAYS, dayMs, type SkylineDay } from '../geometry/skyline'

export interface ReadoutPart {
  key: (typeof TOKEN_SERIES)[number]['key']
  label: string
  /** CSS custom property holding the series colour, e.g. "--sky-color-data-1". */
  token: string
  value: number
  /** "4.56M". */
  display: string
  /** Flex weight for the split bar: never below 0.8% of the total, so a sliver stays visible. */
  flex: number
}

export interface DayReadoutModel {
  date: string
  /** "Fri, Aug 28". */
  dateLabel: string
  /** "2026". */
  year: string
  sessions: string
  executions: string
  commits: string
  /** "5.67M". */
  tokens: string
  /** "$4.98", or an em dash when unknown. */
  cost: string
  parts: ReadoutPart[]
  hasTokens: boolean
  /** "2 failed" when the day has failed runs; null when none or unknown (the readout omits it). */
  failed: string | null
}

const count = (v: number | null | undefined) => (typeof v === 'number' && Number.isFinite(v) ? String(Math.round(v)) : '0')

export function dayReadout(day: SkylineDay): DayReadoutModel {
  const d = new Date(dayMs(day.date))
  const t = day.tokens ?? { input: 0, output: 0, cacheWrite: 0, cacheRead: 0 }
  const total = t.input + t.output + t.cacheWrite + t.cacheRead
  const parts = TOKEN_SERIES.map((s) => ({
    key: s.key,
    label: s.label,
    token: s.token,
    value: t[s.key],
    display: formatTokens(t[s.key], { case: 'upper' }),
    flex: Math.max(t[s.key], total * 0.008),
  }))
  return {
    date: day.date,
    dateLabel: `${WEEKDAYS[d.getUTCDay()]}, ${MONTHS[d.getUTCMonth()]} ${d.getUTCDate()}`,
    year: String(d.getUTCFullYear()),
    sessions: count(day.sessions),
    executions: count(day.executions),
    commits: count(day.commits),
    tokens: formatTokens(total, { case: 'upper' }),
    cost: day.costUsd === null || day.costUsd === undefined ? '—' : formatCost(day.costUsd),
    parts,
    hasTokens: total > 0,
    failed: day.failed ? `${Math.round(day.failed)} failed` : null,
  }
}
