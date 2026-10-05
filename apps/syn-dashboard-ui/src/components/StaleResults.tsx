/**
 * Rows that answer a filter the operator has already changed.
 *
 * Swapping them for a page loader would blank the list on every filter change
 * and throw away the operator's place; leaving them untouched read as a filter
 * that did nothing ("it looks like it's not working"). So they stay, dimmed and
 * inert, under a "Updating" status until the new answer replaces them.
 *
 * A failed request does not end that: the rows still answer the old filter, so
 * they stay dimmed and the status says the update failed, with a retry.
 *
 * Whether the rows are stale is `useServerList`'s call, not this component's.
 */

import { clsx } from 'clsx'
import type { ReactNode } from 'react'
import { Loader } from './Loader'

interface StaleResultsProps {
  stale: boolean
  /** The latest request for the current filters failed. */
  failed?: boolean
  onRetry?: () => void
  children: ReactNode
}

const BADGE =
  'absolute left-1/2 top-4 z-10 flex -translate-x-1/2 items-center gap-2 rounded-full border border-[var(--color-border)] bg-[var(--color-surface-elevated)] px-3 py-1 text-xs shadow'

export function StaleResults({ stale, failed = false, onRetry, children }: StaleResultsProps) {
  return (
    <div className="relative" aria-busy={stale && !failed}>
      {failed ? (
        <div role="alert" className={clsx(BADGE, 'text-[var(--color-error)]')}>
          Couldn&apos;t update these results.
          {onRetry && (
            <button type="button" onClick={onRetry} className="font-medium underline">
              Retry
            </button>
          )}
        </div>
      ) : (
        stale && (
          <div role="status" className={clsx(BADGE, 'text-[var(--color-text-secondary)]')}>
            <Loader size="sm" />
            Updating…
          </div>
        )
      )}
      {/* `inert`, not just `pointer-events-none`: that stops the mouse, but Tab
          would still reach a row control and act on the previous filter. */}
      <div inert={stale} className={clsx('transition-opacity', stale && 'opacity-50')}>
        {children}
      </div>
    </div>
  )
}
