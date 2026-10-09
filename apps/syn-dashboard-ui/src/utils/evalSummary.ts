/**
 * Wording for the eval detail page built from server figures: the Runs card's
 * paging subtitle. The verdict breakdown is in `evalVerdictCounts`.
 */

/** Which slice of an eval's runs a page shows, e.g. "Runs 51–100 of 120, newest first". */
export function runsSubtitle({ page, pageSize, total }: { page: number; pageSize: number; total: number }): string {
  if (total <= pageSize) return `All ${total} runs, newest first`
  const first = (page - 1) * pageSize + 1
  return `Runs ${first}–${Math.min(page * pageSize, total)} of ${total}, newest first`
}
