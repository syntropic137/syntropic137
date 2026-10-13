/**
 * Verifier ranking (Landing section 04 eval explorer; the Evals list later):
 * rank verifiers by quality per dollar and say in one line how the chosen
 * one is doing. Ported from EXPLORER_JS in design/reference/gen_landing3.py.
 *
 * Per verifier: score is the mean of the last 3 judged runs (rounded), cost
 * the mean of the last 3 runs, delta the score against the mean of the
 * first 3 judged runs, cost change against the first 3 runs. A verifier
 * with fewer than FRESH_RUNS runs is "New" and can't be the best pick.
 */
import { formatCost, pointsPerDollar, pointsPerDollarValue } from '../../format/cost'
import { formatSignedPoints } from '../../format/signed'
import { UNKNOWN } from '../../format/shared'
import type { TrendTone } from './trend'

/** Runs averaged at each end. */
export const RANK_WINDOW = 3
/** Fewer runs than this and the trend isn't trusted yet. */
export const FRESH_RUNS = 5
/** Score points that count as improving or slipping. */
export const RANK_SCORE_MOVE = 5
/** USD per run that counts as cheaper or dearer. */
export const RANK_COST_MOVE = 0.03

export interface RankRunLike {
  /** Judge score 0..100; null when the run wasn't scored. */
  score: number | null | undefined
  costUsd: number
}

export interface RankVerifierInput {
  name: string
  /** Runs, oldest first. */
  runs: readonly RankRunLike[]
}

export interface VerifierStats {
  /** Position in the input, for colours and selection. */
  index: number
  name: string
  score: number | null
  cost: number
  delta: number
  costDelta: number
  /** Score per dollar; null without a score or a cost. */
  per: number | null
  runs: number
  fresh: boolean
}

export type RankWord = 'New' | 'Improving' | 'Slipping' | 'Steady'

export interface RankRow {
  /** 1-based rank. */
  rank: number
  index: number
  name: string
  score: string
  cost: string
  /** "168 pts/$". */
  per: string
  word: RankWord
  tone: TrendTone
  best: boolean
  /** "Best quality per dollar" on the best row, else "". */
  bestText: string
}

export interface RankVerdict {
  index: number
  name: string
  score: string
  cost: string
  /** "+15 pts". */
  delta: string
  /** "Up 15 points since its first runs, and $0.17 cheaper per run." */
  line: string
}

export interface VerifierRanking {
  stats: VerifierStats[]
  rows: RankRow[]
  /** Index of the best quality per dollar among trusted verifiers; null when none is. */
  best: number | null
}

const mean = (xs: readonly number[]) => (xs.length ? xs.reduce((a, v) => a + v, 0) / xs.length : 0)

/** The numbers behind one verifier's row. */
export function verifierStats(v: RankVerifierInput, index: number): VerifierStats {
  const scored = v.runs.flatMap((r) => (typeof r.score === 'number' ? [r.score] : []))
  const costs = v.runs.map((r) => r.costUsd)
  const score = scored.length ? Math.round(mean(scored.slice(-RANK_WINDOW))) : null
  const cost = mean(costs.slice(-RANK_WINDOW))
  const delta = score === null ? 0 : score - Math.round(mean(scored.slice(0, RANK_WINDOW)))
  return {
    index,
    name: v.name,
    score,
    cost,
    delta,
    costDelta: cost - mean(costs.slice(0, RANK_WINDOW)),
    per: pointsPerDollarValue(score, cost),
    runs: v.runs.length,
    fresh: v.runs.length < FRESH_RUNS,
  }
}

function word(s: VerifierStats): { word: RankWord; tone: TrendTone } {
  if (s.fresh) return { word: 'New', tone: 'neutral' }
  if (s.delta >= RANK_SCORE_MOVE) return { word: 'Improving', tone: 'good' }
  if (s.delta <= -RANK_SCORE_MOVE) return { word: 'Slipping', tone: 'bad' }
  return { word: 'Steady', tone: 'neutral' }
}

/** Rank verifiers by quality per dollar, best first. */
export function rankVerifiers(verifiers: readonly RankVerifierInput[]): VerifierRanking {
  const stats = verifiers.map(verifierStats)
  const trusted = stats.filter((s) => !s.fresh && s.per !== null)
  const best = trusted.length ? trusted.reduce((a, b) => ((b.per ?? 0) > (a.per ?? 0) ? b : a)).index : null
  const order = [...stats].sort((a, b) => (b.per ?? -Infinity) - (a.per ?? -Infinity))
  const rows = order.map((s, n): RankRow => {
    const isBest = s.index === best
    return {
      rank: n + 1,
      index: s.index,
      name: s.name,
      score: s.score === null ? UNKNOWN : String(s.score),
      cost: formatCost(s.cost),
      per: pointsPerDollar(s.score, s.cost),
      ...word(s),
      best: isBest,
      bestText: isBest ? 'Best quality per dollar' : '',
    }
  })
  return { stats, rows, best }
}

function qualityClause(s: VerifierStats): string {
  if (s.delta >= RANK_SCORE_MOVE) return `Up ${s.delta} points since its first runs`
  if (s.delta <= -RANK_SCORE_MOVE) return `Down ${Math.abs(s.delta)} points since its first runs`
  return 'Holding steady on quality'
}

function costClause(s: VerifierStats): string {
  if (s.costDelta < -RANK_COST_MOVE) return `, and ${formatCost(Math.abs(s.costDelta))} cheaper per run.`
  if (s.costDelta > RANK_COST_MOVE) return `, while costing ${formatCost(s.costDelta)} more per run.`
  return ', at the same cost.'
}

/** The one-line verdict on a verifier: quality first, then what it costs. */
export function verdictLine(s: VerifierStats): string {
  if (s.fresh) return `Only ${s.runs} ${s.runs === 1 ? 'run' : 'runs'} so far. Give it a week before trusting the trend.`
  return qualityClause(s) + costClause(s)
}

/** The readout under the ranking for the selected verifier. */
export function rankVerdict(s: VerifierStats): RankVerdict {
  return {
    index: s.index,
    name: s.name,
    score: s.score === null ? UNKNOWN : String(s.score),
    cost: formatCost(s.cost),
    delta: formatSignedPoints(s.delta),
    line: verdictLine(s),
  }
}
