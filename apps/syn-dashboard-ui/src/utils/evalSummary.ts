/**
 * Wording for the eval detail page that is built from server figures: the
 * verdict breakdown under "Runs scored" and the Runs card's paging subtitle.
 *
 * Counts come from the server's stats over ALL of an eval's runs, never from
 * the page of runs on screen.
 */

import type { EvalRunStats } from '../api/evals'

/** "2 PASS · 1 FAIL · 1 ERROR · 4 unscored": every population, zeros included. */
export function verdictBreakdown(stats: EvalRunStats): string {
  return `${stats.pass_count} PASS · ${stats.fail_count} FAIL · ${stats.error_count} ERROR · ${stats.unscored_count} unscored`
}

/** PASS + FAIL: the runs a pass rate is a fraction of. ERROR and unscored are not. */
export function judgedCount(stats: EvalRunStats): number {
  return stats.pass_count + stats.fail_count
}

/** Which slice of an eval's runs a page shows, e.g. "Runs 51–100 of 120, newest first". */
export function runsSubtitle({ page, pageSize, total }: { page: number; pageSize: number; total: number }): string {
  if (total <= pageSize) return `All ${total} runs, newest first`
  const first = (page - 1) * pageSize + 1
  return `Runs ${first}–${Math.min(page * pageSize, total)} of ${total}, newest first`
}
