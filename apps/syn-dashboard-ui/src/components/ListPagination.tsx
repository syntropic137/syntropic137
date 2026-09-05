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
 */

export interface ListPaginationProps {
  page: number
  pageSize: number
  /** Rows matching the filters across every page, from the server. */
  total: number
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
  onPageChange,
  itemLabel,
}: ListPaginationProps) {
  if (total === 0) return null
  const totalPages = Math.max(1, Math.ceil(total / pageSize))
  const first = (page - 1) * pageSize + 1
  const last = Math.min(page * pageSize, total)
  const noun = total === 1 ? itemLabel : `${itemLabel}s`

  return (
    <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
      <span className="text-sm text-[var(--color-text-secondary)]">
        Showing {first}-{last} of {total} {noun}
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
