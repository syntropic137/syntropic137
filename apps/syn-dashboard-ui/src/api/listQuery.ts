/**
 * The one query the list surfaces ask, and the one shape they answer with.
 *
 * `/executions` and `/sessions` accept the same filters, page the same way, and
 * return the same three facts about a query (the page's rows, how many rows
 * match in total, how the matching rows break down by status). They drifted
 * anyway: `/sessions` sent the time window to the server while `/executions`
 * filtered by it in the browser over 50 already-fetched rows, so the same
 * window meant two different things depending on which page you were on
 * (#1159).
 *
 * Spelling the wire format once is what stops that recurring. A caller
 * describes the query it wants; it never writes a parameter name.
 */

/** A page of a filtered collection, asked for. */
export interface ListQuery {
  page: number
  page_size: number
  /** OR'd status filter. Empty or absent means every status. */
  statuses?: string[]
  /**
   * Inclusive lower bound on started_at, ISO 8601 WITH an offset.
   *
   * The API rejects a timezone-less bound with 422 (#1183), so build these
   * with `timeWindowToStartedAfter` rather than by hand.
   */
  started_after?: string
  /** Inclusive upper bound on started_at, same offset requirement. */
  started_before?: string
  /** Case-insensitive substring match; the server decides which fields. */
  q?: string
}

/** A page of a filtered collection, answered. */
export interface ListPage<TRow> {
  /** This page only. */
  rows: TRow[]
  /**
   * Rows matching every filter, across all pages.
   *
   * Never `rows.length` — that number says "you have them all" however much
   * of the collection is still unreached.
   */
  total: number
  /**
   * Matching rows tallied by status, ignoring the status filter itself.
   *
   * Counted by the server over the whole collection, so a chip reports what
   * selecting it would get you rather than how many of that status happen to
   * be on the page in front of you.
   */
  statusCounts: Record<string, number>
}

/** Serialise a query into the query string both endpoints parse. */
export function listQueryParams(query: ListQuery): URLSearchParams {
  const params = new URLSearchParams()
  params.set('page', String(query.page))
  params.set('page_size', String(query.page_size))
  if (query.statuses && query.statuses.length > 0) {
    params.set('statuses', query.statuses.join(','))
  }
  if (query.started_after) params.set('started_after', query.started_after)
  if (query.started_before) params.set('started_before', query.started_before)
  if (query.q) params.set('q', query.q)
  return params
}
