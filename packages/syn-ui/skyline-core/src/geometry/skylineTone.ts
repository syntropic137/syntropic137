/**
 * Skyline bar colour (owner tweak after demo): height says how busy a day
 * was, colour says how it went. The tone picks the bar's base colour and
 * extrudeColors() lights the top face from it, so the top reads strongest.
 *
 * With outcome counts a day is pass (only completed runs), fail (only
 * failed), mixed (both) or none (sessions but no finished run). Without
 * outcome data the top falls back to a four-step ramp of the accent by
 * session count, like a contribution heatmap. Every fill is a CSS custom
 * property expression, never a colour literal.
 */

/** Finished runs on a day. */
export interface SkylineOutcomes {
  passed: number
  failed: number
}

export type SkylineOutcomeTone = 'pass' | 'fail' | 'mixed' | 'none'
export type SkylineRampTone = 'level-1' | 'level-2' | 'level-3' | 'level-4'
export type SkylineTone = SkylineOutcomeTone | SkylineRampTone

export const SKYLINE_RAMP: readonly SkylineRampTone[] = ['level-1', 'level-2', 'level-3', 'level-4']
export const SKYLINE_OUTCOMES: readonly SkylineOutcomeTone[] = ['pass', 'mixed', 'fail', 'none']

/** Base colour per tone: the status tokens, or the accent mixed toward the empty block. */
export const SKYLINE_TONE_FILL: Record<SkylineTone, string> = {
  pass: 'var(--sky-status-completed)',
  fail: 'var(--sky-status-failed)',
  mixed: 'var(--sky-status-interrupted)',
  none: 'var(--sky-status-pending)',
  'level-1': 'color-mix(in oklab, var(--ds-color-accent) 38%, var(--sky-color-empty))',
  'level-2': 'color-mix(in oklab, var(--ds-color-accent) 58%, var(--sky-color-empty))',
  'level-3': 'color-mix(in oklab, var(--ds-color-accent) 80%, var(--sky-color-empty))',
  'level-4': 'var(--ds-color-accent)',
}

export const SKYLINE_TONE_LABEL: Record<SkylineTone, string> = {
  pass: 'All passed',
  mixed: 'Mixed',
  fail: 'All failed',
  none: 'No finished runs',
  'level-1': 'Fewer',
  'level-2': '',
  'level-3': '',
  'level-4': 'More',
}

function outcomeTone(o: SkylineOutcomes): SkylineOutcomeTone {
  const passed = o.passed > 0
  const failed = o.failed > 0
  if (passed && failed) return 'mixed'
  if (failed) return 'fail'
  return passed ? 'pass' : 'none'
}

/** Ramp step 1..4 by share of the busiest day; any active day is at least step 1. */
function rampTone(sessions: number, maxSessions: number): SkylineRampTone {
  const share = maxSessions > 0 ? Math.min(1, sessions / maxSessions) : 1
  const step = Math.min(4, Math.max(1, Math.ceil(share * 4)))
  return SKYLINE_RAMP[step - 1]!
}

/** The colour rule for one day's top face. */
export function skylineTone(day: { sessions: number; outcomes?: SkylineOutcomes | null }, maxSessions: number): SkylineTone {
  return day.outcomes ? outcomeTone(day.outcomes) : rampTone(day.sessions, maxSessions)
}

export interface SkylineLegendItem {
  tone: SkylineTone
  label: string
  fill: string
}

/** Legend for the tones in use: the outcome key when any day has outcomes, else the ramp. */
export function skylineLegend(days: readonly { outcomes?: SkylineOutcomes | null }[]): { kind: 'outcome' | 'ramp'; items: SkylineLegendItem[] } {
  const kind = days.some((d) => d.outcomes) ? 'outcome' : 'ramp'
  const tones: readonly SkylineTone[] = kind === 'outcome' ? SKYLINE_OUTCOMES : SKYLINE_RAMP
  return { kind, items: tones.map((tone) => ({ tone, label: SKYLINE_TONE_LABEL[tone], fill: SKYLINE_TONE_FILL[tone] })) }
}
