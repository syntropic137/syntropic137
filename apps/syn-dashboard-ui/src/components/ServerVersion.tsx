/**
 * The sidebar's version label: which build the API is running, and when it went live.
 *
 * Shows the SERVER's build (`useServerBuild` keeps it current), falling back to
 * the bundle's own version only until the first answer arrives. Hover or
 * keyboard focus opens a tooltip with the deploy time in the viewer's locale
 * and time zone, how long ago that was, and the commit. Escape closes it.
 * When the deployed release is not the one this page was loaded from, a
 * reload prompt appears beside the label.
 */

import { useId, useState } from 'react'

import type { ServerBuild } from '../hooks/useServerBuild'
import { deployedTooltipText, versionLabel } from '../utils/serverBuild'

export function ServerVersion({ build, bundleIsStale }: ServerBuild) {
  const [open, setOpen] = useState(false)
  const tooltipId = useId()
  const showTooltip = open && build !== null

  return (
    <div className="flex items-center justify-end gap-2">
      {bundleIsStale && (
        <button
          type="button"
          onClick={() => window.location.reload()}
          className="truncate text-[11px] text-[var(--color-accent)] hover:underline"
        >
          New version: reload
        </button>
      )}
      <span className="relative">
        <span
          // Focusable so keyboard users reach the tooltip too; it is a label, not a control.
          tabIndex={0}
          aria-describedby={showTooltip ? tooltipId : undefined}
          onMouseEnter={() => setOpen(true)}
          onMouseLeave={() => setOpen(false)}
          onFocus={() => setOpen(true)}
          onBlur={() => setOpen(false)}
          onKeyDown={(e) => {
            if (e.key === 'Escape') setOpen(false)
          }}
          className="block truncate rounded text-xs text-[var(--color-text-muted)] focus:outline-none focus-visible:ring-1 focus-visible:ring-[var(--color-accent)]"
        >
          {versionLabel(build)}
        </span>
        {showTooltip && (
          <span
            id={tooltipId}
            role="tooltip"
            className="absolute bottom-full right-0 z-50 mb-1 w-max max-w-[13rem] rounded-md border border-[var(--color-border)] bg-[var(--color-surface-elevated)] px-2 py-1 text-[11px] text-[var(--color-text-secondary)] shadow-lg"
          >
            {deployedTooltipText(build)}
          </span>
        )}
      </span>
    </div>
  )
}
