/**
 * "2 running / 3 queued / cap 4" in the app bar (PC-124).
 *
 * The text is the server's `display`, so it matches `syn execution list`.
 * Below sm: the full sentence does not fit beside the menu button at 375px,
 * so it compacts to "2/4 · 3 queued" with the sentence kept as the title.
 */

import { clsx } from 'clsx'
import { Link } from 'react-router-dom'

import type { ExecutionBudgetInfo } from '../types'

export function ExecutionBudgetIndicator({
  budget,
  className,
}: {
  budget: ExecutionBudgetInfo | null
  className?: string
}) {
  if (budget === null) return null
  const waiting = budget.queued > 0 || budget.admission_paused === true
  return (
    <Link
      to={budget.queued > 0 ? '/executions?status=queued' : '/executions'}
      title={budget.display}
      aria-label={`Execution budget: ${budget.display}`}
      className={clsx(
        'whitespace-nowrap rounded-md px-2 py-1 font-mono text-[11px] hover:bg-[var(--color-surface-elevated)]',
        waiting ? 'text-amber-500' : 'text-[var(--color-text-muted)]',
        className,
      )}
    >
      <span className="sm:hidden">
        {budget.running}/{budget.limit} · {budget.queued} queued
      </span>
      <span className="hidden sm:inline">{budget.display}</span>
    </Link>
  )
}
