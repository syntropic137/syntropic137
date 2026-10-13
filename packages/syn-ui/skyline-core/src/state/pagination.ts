/**
 * Pagination arithmetic. Pages are 1-based, matching PaginationContract.
 */
export type PageItem = number | 'gap'

export function clampPage(page: number, pageCount: number): number {
  const max = Math.max(1, Math.floor(pageCount) || 1)
  if (!Number.isFinite(page)) return 1
  return Math.min(max, Math.max(1, Math.round(page)))
}

/**
 * Page numbers to draw: always the first and last page, `siblingCount`
 * pages either side of the current one, and 'gap' where pages are skipped.
 * The list length stays constant (2 * siblingCount + 5) once pageCount is
 * large enough, so the control does not jump as the user pages.
 */
export function paginationRange(page: number, pageCount: number, siblingCount = 1): PageItem[] {
  const count = Math.max(1, Math.floor(pageCount) || 1)
  const current = clampPage(page, count)
  const sib = Math.max(0, Math.floor(siblingCount))
  const slots = sib * 2 + 5
  if (count <= slots) return range(1, count)

  const left = Math.max(current - sib, 1)
  const right = Math.min(current + sib, count)
  const showLeftGap = left > 3
  const showRightGap = right < count - 2

  if (!showLeftGap) return [...range(1, 3 + 2 * sib), 'gap', count]
  if (!showRightGap) return [1, 'gap', ...range(count - (2 + 2 * sib), count)]
  return [1, 'gap', ...range(left, right), 'gap', count]
}

/** "Showing 12 of 27": how many items are on screen after `page` pages of `pageSize`. */
export function shownCount(page: number, pageSize: number, total: number): number {
  return Math.max(0, Math.min(total, clampPage(page, Math.ceil(total / Math.max(1, pageSize))) * pageSize))
}

function range(a: number, b: number): number[] {
  const out: number[] = []
  for (let i = a; i <= b; i++) out.push(i)
  return out
}
