/**
 * Example state of the Eval Explorer for /dev/patterns: the Landing board's
 * section 04 (gen_trends.py EVAL_RUNS, sample data). Runs are
 * [day, verifier, cost USD, judge score].
 */
import type { EvalExplorerProps, ExplorerVerifier } from '@syn137/skyline-core/patterns'

const RUNS: readonly [number, number, number, number | null][] = [
  [0, 0, 1.21, 82], [4, 0, 1.18, 85], [8, 0, 1.25, 61], [12, 0, 1.16, 84], [17, 0, 1.09, 88], [21, 0, 1.06, 90], [25, 0, 1.02, 91], [29, 0, 1.04, 92],
  [1, 1, 0.49, 48], [5, 1, 0.51, 55], [9, 1, 0.5, 72], [13, 1, 0.53, 63], [16, 1, 0.52, 66], [19, 1, 0.5, 78], [22, 1, 0.52, 84], [26, 1, 0.51, 87], [28, 1, 0.52, 89],
  [2, 2, 0.55, 80], [7, 2, 0.58, 78], [11, 2, 0.61, 64], [15, 2, 0.63, 76], [20, 2, 0.66, 62], [24, 2, 0.69, 73], [27, 2, 0.71, 58],
  [23, 3, 0.62, 79], [25, 3, 0.6, 66], [27, 3, 0.59, 81], [29, 3, 0.61, null],
]

const NAMES = ['claude-opus-5-5', 'claude-sonnet-5-5', 'gpt-5.6-sol', 'gpt-5.6-terra'] as const

export const EVAL_EXPLORER_VERIFIERS: readonly ExplorerVerifier[] = NAMES.map((name, si) => {
  const runs = RUNS.filter((r) => r[1] === si).sort((a, b) => a[0] - b[0])
  return { name, colour: si + 1, days: runs.map((r) => r[0]), costs: runs.map((r) => r[2]), scores: runs.map((r) => r[3]) }
})

export const EVAL_EXPLORER_EXAMPLE: EvalExplorerProps = {
  verifiers: EVAL_EXPLORER_VERIFIERS,
  passAt: 70,
  judge: 'claude-opus-5-5',
  span: 29,
  ticks: ['Sep 8', 'Sep 15', 'Sep 22', 'Sep 29', 'Oct 7'],
}
