/**
 * Rows that answer a filter the operator has already changed.
 *
 * Swapping them for a page loader would blank the list on every filter change
 * and throw away the operator's place; leaving them untouched read as a filter
 * that did nothing ("it looks like it's not working"). So they stay, dimmed and
 * inert, under a "Updating" status until the new answer replaces them.
 *
 * Whether the rows are stale is `useServerList`'s call, not this component's.
 */

import { clsx } from 'clsx'
import type { ReactNode } from 'react'
import { Loader } from './Loader'

interface StaleResultsProps {
  stale: boolean
  children: ReactNode
}

export function StaleResults({ stale, children }: StaleResultsProps) {
  return (
    <div className="relative" aria-busy={stale}>
      {stale && (
        <div
          role="status"
          className="absolute left-1/2 top-4 z-10 flex -translate-x-1/2 items-center gap-2 rounded-full border border-[var(--color-border)] bg-[var(--color-surface-elevated)] px-3 py-1 text-xs text-[var(--color-text-secondary)] shadow"
        >
          <Loader size="sm" />
          Updating…
        </div>
      )}
      <div className={clsx('transition-opacity', stale && 'pointer-events-none opacity-50')}>
        {children}
      </div>
    </div>
  )
}
