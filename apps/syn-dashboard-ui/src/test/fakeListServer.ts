/**
 * A list endpoint that answers a `ListQuery` the way the real ones do.
 *
 * The point of the paging work is that the browser stops deciding which rows
 * match; the server does. A test double that returns a canned array cannot
 * show that, because it answers the same way whether or not the filters were
 * ever sent. This one filters, tallies, orders and slices from the query it
 * was handed, mirroring `syn_domain.pagination.paginate`:
 *
 *   - `total` counts rows matching EVERY filter, including status
 *   - `status_counts` tallies the same rows IGNORING the status filter, so an
 *     unselected chip still reports what selecting it would get
 *   - rows are ordered newest-first and sliced to the requested page
 *
 * So a hook that forgets to forward a filter, or reads `rows.length` where it
 * should read `total`, produces a visibly wrong answer here.
 */

import type { ListQuery } from '../api/listQuery'

export interface ListRow {
  status: string
  started_at: string
}

export interface ListAnswer<TRow> {
  rows: TRow[]
  total: number
  status_counts: Record<string, number>
}

export function answerListQuery<TRow extends ListRow>(
  collection: readonly TRow[],
  query: ListQuery,
  matchesSearch: (row: TRow, term: string) => boolean = () => true,
): ListAnswer<TRow> {
  const beforeStatus = collection.filter(
    (row) =>
      (!query.started_after || row.started_at >= query.started_after) &&
      (!query.started_before || row.started_at <= query.started_before) &&
      (!query.q || matchesSearch(row, query.q)),
  )

  const status_counts: Record<string, number> = {}
  for (const row of beforeStatus) {
    status_counts[row.status] = (status_counts[row.status] ?? 0) + 1
  }

  const allowed = query.statuses
  const matched = allowed?.length
    ? beforeStatus.filter((row) => allowed.includes(row.status))
    : beforeStatus

  const ordered = [...matched].sort((a, b) => b.started_at.localeCompare(a.started_at))
  const offset = (query.page - 1) * query.page_size

  return {
    rows: ordered.slice(offset, offset + query.page_size),
    total: matched.length,
    status_counts,
  }
}
