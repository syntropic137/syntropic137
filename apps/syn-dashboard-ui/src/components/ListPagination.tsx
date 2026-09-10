/**
 * "Showing 1-50 of 360" plus the controls to reach the other 310.
 *
 * The count is the point, not the buttons. A list that renders one page with
 * no statement of what it is a page OF reads as the whole collection, which is
 * how ~360 executions looked like 50 for as long as it did (#1159). So the
 * line is rendered whenever there is anything to describe, and the buttons
 * only when there is somewhere to go.
 *
 * `total` is the server's count of matching rows. Passing `rows.length` would
 * restate the bug this component exists to make visible.
 *
 * `excludedUndated` is the same argument one step on. When a window is set,
 * `total` silently omits every row whose timestamp could not be read - 274 of
 * 1037 artifacts, all written before their event carried a date (#1215). "of
 * 755" reads as "755 exist"; "of 755 · 274 undated" says what the other number
 * is. It is a separate figure rather than folded into `total` because those
 * rows are genuinely NOT in the window: nobody can say whether they belong in
 * it, and a 24-hour list that includes rows of unknown age is a different lie.
 */

export interface ListPaginationProps {
  page: number
  pageSize: number
  /** Rows matching the filters across every page, from the server. */
  total: number
  /**
   * Matching rows the server could not place in the window, for want of a
   * timestamp. Optional: a surface with no time filter has none, and one that
   * has not been taught to ask for the number should say nothing rather than
   * assert a confident zero.
   */
  excludedUndated?: number
  onPageChange: (page: number) => void
  /** Singular noun for the count, e.g. "execution". */
  itemLabel: string
}

const BUTTON_CLASS =
  'rounded-lg border border-[var(--color-border)] bg-[var(--color-surface)] px-3 py-1.5 text-sm text-[var(--color-text-secondary)] hover:bg-[var(--color-surface-elevated)] disabled:cursor-not-allowed disabled:opacity-50'

export function ListPagination({
  page,
  pageSize,
  total,
  excludedUndated = 0,
  onPageChange,
  itemLabel,
}: ListPaginationProps) {
  // A window that matched nothing but excluded 274 rows is the case the reader
  // most needs this line for, so an empty page is not silent unless there is
  // genuinely nothing to say.
  if (total === 0 && excludedUndated === 0) return null
  const totalPages = Math.max(1, Math.ceil(total / pageSize))
  const first = (page - 1) * pageSize + 1
  const last = Math.min(page * pageSize, total)
  const noun = total === 1 ? itemLabel : `${itemLabel}s`

  return (
    <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
      <span className="text-sm text-[var(--color-text-secondary)]">
        {total > 0 && `Showing ${first}-${last} of ${total} ${noun}`}
        {excludedUndated > 0 && (
          <span
            className="text-[var(--color-text-tertiary)]"
            title="These rows carry no timestamp, so no time window can include or exclude them on the evidence. They are shown when no window is set."
          >
            {total > 0 ? ' · ' : ''}
            {excludedUndated} undated, not judged by this window
          </span>
        )}
      </span>
      {totalPages > 1 && (
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={() => onPageChange(page - 1)}
            disabled={page <= 1}
            className={BUTTON_CLASS}
          >
            Previous
          </button>
          <span className="text-sm text-[var(--color-text-secondary)]">
            Page {page} of {totalPages}
          </span>
          <button
            type="button"
            onClick={() => onPageChange(page + 1)}
            disabled={page >= totalPages}
            className={BUTTON_CLASS}
          >
            Next
          </button>
        </div>
      )}
    </div>
  )
}
