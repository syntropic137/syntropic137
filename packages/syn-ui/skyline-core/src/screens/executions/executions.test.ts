import { describe, expect, it } from 'vitest'
import {
  ageGroupTitle,
  evalBadge,
  parseEvalFilter,
  phaseProgressText,
  isExecutionEvent,
  canCancel,
  costRowsByPhase,
  executionsLede,
  executionsLedeShort,
  groupByAge,
  listSummary,
  outcomeTotals,
  parseTimeWindow,
  DEFAULT_LIST_WINDOW,
  timeWindowParam,
  type PhaseLike,
  phaseKit,
  phaseMeta,
  phaseModelChip,
  phaseTokenSplit,
  provenanceFor,
  runIdentityText,
  shortPhaseName,
  shortRevision,
  timeWindowStart,
  timelineCaption,
  usageNote,
} from './index'

const NOW = Date.parse('2026-10-08T12:00:00Z')
const DAY = 86_400_000

const phase = (o: Partial<PhaseLike> = {}): PhaseLike => ({
  name: 'Discovery Phase',
  status: 'completed',
  input_tokens: 25,
  output_tokens: 1801,
  cache_creation_tokens: 31442,
  cache_read_tokens: 60160,
  duration_seconds: 24.3,
  cost_usd: 0.0557,
  model: null,
  requested_model: 'haiku',
  model_display: 'unknown (requested: haiku)',
  start_pins_status: 'not_recorded',
  pinned_at_start: null,
  ...o,
})

describe('list', () => {
  it('parses and bounds time windows', () => {
    expect(parseTimeWindow('7d')).toBe('7d')
    expect(parseTimeWindow('nope')).toBe('all')
    expect(timeWindowStart('all', NOW)).toBeUndefined()
    expect(timeWindowStart('1h', NOW)).toBe('2026-10-08T11:00:00.000Z')
  })

  it('defaults the lists to 24h; All stays selectable as ?window=all', () => {
    expect(DEFAULT_LIST_WINDOW).toBe('24h')
    expect(parseTimeWindow(null, DEFAULT_LIST_WINDOW)).toBe('24h')
    expect(parseTimeWindow('all', DEFAULT_LIST_WINDOW)).toBe('all')
    expect(parseTimeWindow('bogus', DEFAULT_LIST_WINDOW)).toBe('24h')
    expect(timeWindowParam('24h', DEFAULT_LIST_WINDOW)).toBeNull()
    expect(timeWindowParam('all', DEFAULT_LIST_WINDOW)).toBe('all')
    expect(timeWindowParam('7d', DEFAULT_LIST_WINDOW)).toBe('7d')
    expect(timeWindowParam('all')).toBeNull()
  })

  it('names age groups like the board', () => {
    expect(ageGroupTitle(new Date(NOW - 3_600_000).toISOString(), NOW)).toBe('Today')
    expect(ageGroupTitle(NOW - 1.5 * DAY, NOW)).toBe('Yesterday')
    expect(ageGroupTitle(NOW - 8 * DAY, NOW)).toBe('Last week')
    expect(ageGroupTitle(NOW - 43 * DAY, NOW)).toBe('6 weeks ago')
    expect(ageGroupTitle(null, NOW)).toBe('Undated')
  })

  it('groups consecutive rows and counts them', () => {
    const rows = [NOW - 8 * DAY, NOW - 9 * DAY, NOW - 43 * DAY].map((t) => ({ t: new Date(t).toISOString() }))
    const groups = groupByAge(rows, (r) => r.t, NOW)
    expect(groups.map((g) => [g.title, g.count])).toEqual([
      ['Last week', '2 runs'],
      ['6 weeks ago', '1 run'],
    ])
  })

  it('folds status counts and writes the lede', () => {
    const t = outcomeTotals({ completed: 50, failed: 23, cancelled: 2 })
    expect(t).toMatchObject({ total: 75, completed: 50, failed: 23, cancelled: 2, running: 0 })
    expect(executionsLede(t)).toBe('Every workflow run, newest first. 75 so far, none running.')
    expect(executionsLedeShort(t)).toBe('75 runs, none running now')
    expect(executionsLede({ total: 3, running: 1 })).toContain('1 running')
  })

  it('summarises a page', () => {
    expect(listSummary(1, 50, 19, 75)).toBe('Showing 1–19 of 75 executions')
    expect(listSummary(2, 50, 25, 75, 'failed')).toBe('Showing 51–75 of 75 failed executions')
    expect(listSummary(1, 50, 0, 0)).toBe('No executions')
  })
})

describe('detail', () => {
  it('splits tokens and writes phase meta', () => {
    expect(phaseTokenSplit(phase())).toBe('60.2K read · 31.4K write · 1.8K out · 25 in')
    const m = phaseMeta(phase())
    expect(m.metaShort).toBe('24.3s')
    expect(m.meta).toBe('24.3s · 93.4K tokens · $0.0557')
    expect(m.phone).toBe('24.3s · 93.4K tokens')
  })

  it('sums the timeline', () => {
    const ps = [phase({ duration_seconds: 24.3 }), phase({ duration_seconds: 118.9 }), phase({ duration_seconds: 80.6 })]
    expect(timelineCaption(ps)).toBe('223.8s inside phases.')
    expect(timelineCaption([phase({ duration_seconds: null })])).toBeNull()
  })

  it('chips the model', () => {
    expect(phaseModelChip(phase())).toBe('Claude · haiku requested')
    expect(phaseModelChip(phase({ model: 'claude-haiku-4-5' }))).toBe('claude-haiku-4-5')
    // Never a model that was not observed (feedback 58868cd8).
    expect(phaseModelChip(phase({ requested_model: null, model_display: 'unknown' }))).toBe('model not reported')
  })

  it('reads the kit from start pins', () => {
    expect(phaseKit(phase())).toEqual({ tools: 'not-recorded', skills: 'not-recorded' })
    const kit = phaseKit(
      phase({
        start_pins_status: 'recorded',
        pinned_at_start: { provider: 'claude', allowed_tools: [], skills: [{ name: 'scribe', version: 'main', resolved_sha: 'abc', source_url: 'x/y' }] },
      }),
    )
    expect(kit.tools).toBe('default')
    expect(kit.skills).toEqual([{ name: 'scribe', source: 'x/y', ref: 'main', digest: 'abc' }])
  })

  it('shortens phase names for cost rows', () => {
    expect(shortPhaseName('Discovery Phase')).toBe('Discovery')
    expect(shortPhaseName('Deep Dive Analysis')).toBe('Deep Dive')
    expect(shortPhaseName('Synthesis & Documentation')).toBe('Synthesis')
    expect(costRowsByPhase([phase()])).toEqual([{ label: '01 Discovery', value: 0.0557, tone: 'accent' }])
    // The live API sends Decimal as a string; the meter needs a number for its bars and shares.
    expect(costRowsByPhase([phase({ cost_usd: '0.3480798' })])[0]!.value).toBe(0.3480798)
  })

  it('notes an unknown model', () => {
    expect(usageNote([phase(), phase(), phase()])).toBe('Model unknown: all three phases requested haiku, and the cost is not attributed to a model.')
    expect(usageNote([phase({ model: 'claude-haiku-4-5' })])).toBeUndefined()
  })

  it('builds provenance with and without an inventory', () => {
    const bare = provenanceFor([phase(), phase({ status: 'pending' })], null)
    expect(bare.counts.platformSessions).toBe(1)
    expect(bare.actionLabel).toBeNull()
    const full = provenanceFor([phase()], {
      reconstruction_status: 'current',
      later_evidence_pending: false,
      summary: {
        complete: false,
        coverage_state: 'unsupported',
        coverage_display: 'Missing host registration affects all 3.',
        revision: 'f82315509573aaaaaaaaaaaaaaaab742d4d5',
        platform_sessions: 3,
        native_transcripts: 0,
        invocations: 0,
        gaps: 1,
        remote_replication: 'disabled',
      },
    })
    expect(full.warning?.lead).toBe("Coverage can't be proven for this harness.")
    expect(full.facts).toEqual(['revision f82315509573…b742d4d5', 'reconstruction current', 'remote replication off'])
    expect(shortRevision('short')).toBe('short')
  })

  it('copies identity and gates cancel', () => {
    const text = runIdentityText({ workflow_execution_id: 'exec-1', workflow_id: 'wf', workflow_name: 'Research', status: 'completed', started_at: null, repos: ['a/b'] })
    expect(text).toBe('execution: exec-1\nworkflow: Research (wf)\nstatus: completed\nrepos: a/b')
    expect(canCancel('running')).toBe(true)
    expect(canCancel('queued')).toBe(true)
    expect(canCancel('completed')).toBe(false)
  })
})

describe('isExecutionEvent', () => {
  it("matches the API's real event_type names, not snake_case guesses", () => {
    for (const t of ['WorkflowExecutionStarted', 'WorkflowCompleted', 'WorkflowFailed', 'PhaseStarted', 'PhaseCompleted']) expect(isExecutionEvent(t)).toBe(true)
    for (const t of ['SessionStarted', 'git_commit', 'connected']) expect(isExecutionEvent(t)).toBe(false)
  })
})

describe('eval marker and progress text', () => {
  it('marks a run that belongs to an eval (feedback 4df2bfc9)', () => {
    expect(evalBadge(null)).toBeNull()
    expect(evalBadge(undefined)).toBeNull()
    expect(evalBadge({ eval_id: 'eval-1', eval_name: 'verifier-seed: x', association_kind: 'launched', verdict: 'PASS', score: 1 })).toEqual({
      label: 'Eval',
      title: 'Eval run of verifier-seed: x (launched) · verdict PASS',
      href: '/evals/eval-1',
    })
    expect(evalBadge({ eval_id: 'eval-2' })?.title).toBe('Eval run of eval-2 · not scored yet')
    expect(parseEvalFilter('1')).toBe(true)
    expect(parseEvalFilter(null)).toBe(false)
  })
  it('writes header progress from the same plan the phase list draws (feedback 9a95d8f7)', () => {
    expect(phaseProgressText('phase 2 of up to 8', 1, 8)).toBe('phase 2 of up to 8')
    expect(phaseProgressText('3 of up to 10, failed', 3, 10)).toBe('phases 3 of up to 10, failed')
    expect(phaseProgressText(null, 1, 3)).toBe('1 of 3 phases')
    expect(phaseProgressText(undefined, 0, 1)).toBe('0 of 1 phase')
  })
})
