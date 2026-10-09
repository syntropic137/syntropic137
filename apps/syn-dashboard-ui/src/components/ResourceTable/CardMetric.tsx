/**
 * One labelled value in a ResourceCardList card's metric grid.
 *
 * A grid item's minimum width is its content, so an unbroken value such as a
 * repo list widened its column past the card and ran into the cell beside it
 * on a phone (feedback fc9f69a0, 5f2359cd). The cell is allowed to shrink and
 * the value truncates on one line, with the full text in its tooltip.
 */

import { clsx } from 'clsx'

interface CardMetricProps {
  label: string
  value: string
  /** Span the whole grid row: for values, like a repo list, that are long by nature. */
  wide?: boolean
}

export function CardMetric({ label, value, wide = false }: CardMetricProps) {
  return (
    <div className={clsx('min-w-0', wide && 'col-span-full')}>
      <div className="text-[10px] uppercase tracking-wide text-[var(--color-text-muted)]">
        {label}
      </div>
      <div className="truncate font-mono text-xs text-[var(--color-text-primary)]" title={value}>
        {value}
      </div>
    </div>
  )
}
