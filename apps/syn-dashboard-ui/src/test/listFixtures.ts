/**
 * Collections that do not fit on one page.
 *
 * This is the whole of why #1159, #1160 and #1204 shipped. At 50 rows or
 * fewer, "fetch one page" and "fetch the collection" are the same program:
 * `total` and `rows.length` agree, page 2 is empty either way, and every
 * assertion passes against the correct implementation and the broken one
 * alike. No dashboard fixture was ever bigger than a page, so nothing could
 * tell the two apart.
 *
 * So both collections here are 120 rows - three pages at `LIST_PAGE_SIZE` -
 * and are aged so that the windows a test switches between BOTH overflow a
 * page:
 *
 *   000-029   under 24h        the default window holds 30
 *   030-079   1-7 days old     7d holds 80, more than one page
 *   080-119   older than 7d    All holds 120, also more than one page
 *
 * That last property is the difficult one. Widening a lower bound on a
 * newest-first list CANNOT change the first page, so a fixture whose narrow
 * window fits on one page quietly dodges the case: the rows visibly change and
 * the test passes for a reason that has nothing to do with the bug.
 *
 * Statuses and types are dealt so the largest facet alone exceeds a page,
 * which is what makes a facet count that was tallied over the page rather than
 * the collection visibly wrong.
 */

export const HOUR_MS = 60 * 60 * 1000
export const DAY_MS = 24 * HOUR_MS

/** Three pages at `LIST_PAGE_SIZE`, so the last one is a partial page. */
const COLLECTION_SIZE = 120

/** Age of row `index`, dealt across the three bands described above. */
function hoursAgo(index: number): number {
  if (index < 30) return (index + 1) * 0.5
  if (index < 80) return 25 + (index - 30) * 2
  return 200 + (index - 80) * 24
}

function isoAgo(ms: number): string {
  return new Date(Date.now() - ms).toISOString()
}

/**
 * The rows a window of `ms` holds, derived from the fixture rather than
 * written down - a hand-counted expectation stops agreeing the moment the
 * shape above is adjusted, and does so silently.
 */
export function within<TRow>(
  rows: readonly TRow[],
  ms: number,
  at: (row: TRow) => string,
): TRow[] {
  const bound = isoAgo(ms)
  return rows.filter((row) => at(row) >= bound)
}

/** Tally rows by any facet, the way the server does: over all of them. */
export function tally<TRow>(
  rows: readonly TRow[],
  facetOf: (row: TRow) => string,
): Record<string, number> {
  const counts: Record<string, number> = {}
  for (const row of rows) counts[facetOf(row)] = (counts[facetOf(row)] ?? 0) + 1
  return counts
}

export interface FakeExecution {
  workflow_execution_id: string
  workflow_id: string
  workflow_name: string
  status: string
  started_at: string
  completed_at: string | null
  completed_phases: number
  total_phases: number
  total_tokens: number
  total_tokens_display: string
  total_input_tokens: number
  total_output_tokens: number
  total_cache_creation_tokens: number
  total_cache_read_tokens: number
  total_cost_usd: string
  total_cost_display: string
  unpriced_observation_count: number
  duration_seconds: number | null
  duration_display: string
  tool_call_count: number
  repos: string[]
}

function makeExecution(index: number): FakeExecution {
  return {
    workflow_execution_id: `exec-${String(index).padStart(3, '0')}`,
    workflow_id: 'wf-1',
    workflow_name: `Run ${String(index).padStart(3, '0')}`,
    // Every status here is terminal, so nothing on screen is still moving and
    // `useRefetchWhileRunning` never starts a 3s poll under the assertions.
    status: index % 5 === 0 ? 'failed' : index % 17 === 0 ? 'cancelled' : 'completed',
    started_at: isoAgo(hoursAgo(index) * HOUR_MS),
    completed_at: null,
    completed_phases: 1,
    total_phases: 1,
    total_tokens: 10,
    total_tokens_display: '10',
    total_input_tokens: 5,
    total_output_tokens: 5,
    total_cache_creation_tokens: 0,
    total_cache_read_tokens: 0,
    total_cost_usd: '0',
    total_cost_display: '$0.00',
    unpriced_observation_count: 0,
    duration_seconds: 1,
    duration_display: '1s',
    tool_call_count: 0,
    repos: [],
  }
}

/** 120 executions, newest first. */
export const EXECUTIONS: readonly FakeExecution[] = Array.from(
  { length: COLLECTION_SIZE },
  (_, index) => makeExecution(index),
)

export function matchesExecutionSearch(row: FakeExecution, term: string): boolean {
  const needle = term.toLowerCase()
  return (
    row.workflow_execution_id.toLowerCase().includes(needle) ||
    row.workflow_id.toLowerCase().includes(needle) ||
    row.workflow_name.toLowerCase().includes(needle)
  )
}

export interface FakeArtifact {
  id: string
  workflow_id: string | null
  phase_id: string | null
  artifact_type: string
  title: string | null
  size_bytes: number
  /** Never null here: it is what the window bounds and what orders the list. */
  created_at: string
}

function makeArtifact(index: number): FakeArtifact {
  return {
    id: `art-${String(index).padStart(3, '0')}`,
    workflow_id: 'wf-1',
    phase_id: `phase-${index % 3}`,
    artifact_type: index % 5 === 0 ? 'log' : index % 17 === 0 ? 'report' : 'deliverable',
    title: `Artifact ${String(index).padStart(3, '0')}`,
    size_bytes: 100 + index,
    created_at: isoAgo(hoursAgo(index) * HOUR_MS),
  }
}

/** 120 artifacts, aged exactly as the executions are. */
export const ARTIFACTS: readonly FakeArtifact[] = Array.from(
  { length: COLLECTION_SIZE },
  (_, index) => makeArtifact(index),
)

export function matchesArtifactSearch(row: FakeArtifact, term: string): boolean {
  const needle = term.toLowerCase()
  return (
    row.id.toLowerCase().includes(needle) || (row.title?.toLowerCase().includes(needle) ?? false)
  )
}
