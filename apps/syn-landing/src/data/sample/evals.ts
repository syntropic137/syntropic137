/**
 * SAMPLE DATA, not real results. The eval explorer in "04 Compounding
 * improvement" (design/canvas/Landing.dc.html, section #evals) draws these
 * made-up runs: four verifiers replaying one captured bug over 30 days
 * (Sep 8 = day 0 to Oct 7 = day 29), each run scored 0 to 100 by the judge,
 * with its cost in USD. Source: EVAL_RUNS in design/reference/gen_trends.py.
 */
import type { SkyEvalExplorerProperties } from "@syn137/skyline-svelte-v5/elements";

export const EVAL_SAMPLE: SkyEvalExplorerProperties = {
  judge: "claude-opus-5-5",
  passAt: 70,
  span: 29,
  costMax: 1.6,
  ticks: ["Sep 8", "Sep 15", "Sep 22", "Sep 29", "Oct 7"],
  verifiers: [
    {
      name: "claude-opus-5-5",
      colour: 1,
      days: [0, 4, 8, 12, 17, 21, 25, 29],
      scores: [82, 85, 61, 84, 88, 90, 91, 92],
      costs: [1.21, 1.18, 1.25, 1.16, 1.09, 1.06, 1.02, 1.04],
    },
    {
      name: "claude-sonnet-5-5",
      colour: 2,
      days: [1, 5, 9, 13, 16, 19, 22, 26, 28],
      scores: [48, 55, 72, 63, 66, 78, 84, 87, 89],
      costs: [0.49, 0.51, 0.5, 0.53, 0.52, 0.5, 0.52, 0.51, 0.52],
    },
    {
      name: "gpt-5.6-sol",
      colour: 3,
      days: [2, 7, 11, 15, 20, 24, 27],
      scores: [80, 78, 64, 76, 62, 73, 58],
      costs: [0.55, 0.58, 0.61, 0.63, 0.66, 0.69, 0.71],
    },
    {
      name: "gpt-5.6-terra",
      colour: 4,
      days: [23, 25, 27, 29],
      // The last run has not been scored yet.
      scores: [79, 66, 81, null],
      costs: [0.62, 0.6, 0.59, 0.61],
    },
  ],
};
