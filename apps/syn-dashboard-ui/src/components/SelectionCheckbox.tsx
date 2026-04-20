/**
 * Wrapper around the native checkbox with `indeterminate` support.
 *
 * Native input keeps a11y / keyboard / focus / touch handling correct on every
 * platform — we just style it. Click handler stops propagation so the
 * surrounding row/card click doesn't fire.
 *
 * See: docs/adrs/ADR-064-observability-monitor-ui.md
 */

import { clsx } from 'clsx'
import type { MouseEvent } from 'react'
import { useEffect, useRef } from 'react'

interface SelectionCheckboxProps {
  checked: boolean
  indeterminate?: boolean
  onChange: (event: MouseEvent<HTMLInputElement>) => void
  ariaLabel: string
  className?: string
}

export function SelectionCheckbox({
  checked,
  indeterminate = false,
  onChange,
  ariaLabel,
  className,
}: SelectionCheckboxProps) {
  const ref = useRef<HTMLInputElement | null>(null)

  useEffect(() => {
    if (ref.current) ref.current.indeterminate = indeterminate
  }, [indeterminate])

  return (
    <input
      ref={ref}
      type="checkbox"
      checked={checked}
      onClick={(e) => {
        e.stopPropagation()
        onChange(e)
      }}
      onChange={() => {
        /* state is parent-owned — handled in onClick to capture modifiers */
      }}
      aria-label={ariaLabel}
      className={clsx('selection-checkbox', className)}
    />
  )
}
