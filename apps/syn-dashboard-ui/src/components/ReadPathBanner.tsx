/**
 * The shell's read-path banners: a read model rebuilding (wait, it ends by
 * itself), and a projection held or the subscription halted (stuck, needs a
 * person). Shown independently, because a hold during a rebuild is both.
 *
 * Non-blocking: they sit above the page and never cover it. All wording that
 * carries a number comes from the API's `*_display` fields.
 */

import { AlertOctagon, RefreshCw } from 'lucide-react'

import type { ReadModelStatus } from '../api'
import type { ReadPathHealth } from '../hooks/useReadPathHealth'

function RebuildingBanner({ rebuilding }: { rebuilding: ReadModelStatus[] }) {
  const [first, ...rest] = rebuilding
  return (
    <div
      role="status"
      data-testid="read-path-rebuilding"
      className="flex items-start gap-2 rounded-md border border-blue-500/20 bg-blue-500/10 px-3 py-2 text-sm text-blue-300"
    >
      <RefreshCw aria-hidden="true" className="mt-0.5 h-4 w-4 shrink-0 animate-spin [animation-duration:3s]" />
      <p className="min-w-0 break-words">
        {first.summary_display} Recent results will appear shortly.
        {rest.length > 0 && (
          <span className="text-blue-300/70">
            {' '}
            Also rebuilding: {rest.map((status) => `${status.label_display} (${status.progress_display})`).join(', ')}.
          </span>
        )}
      </p>
    </div>
  )
}

function StuckBanner({ held, haltedAt }: Pick<ReadPathHealth, 'held' | 'haltedAt'>) {
  return (
    <div
      role="alert"
      data-testid="read-path-stuck"
      className="flex items-start gap-2 rounded-md border border-[var(--color-error)]/30 bg-[var(--color-error)]/10 px-3 py-2 text-sm text-[var(--color-error)]"
    >
      <AlertOctagon aria-hidden="true" className="mt-0.5 h-4 w-4 shrink-0" />
      <div className="min-w-0 break-words">
        {haltedAt !== null && (
          <p>
            Event processing is halted at event #{haltedAt}, which cannot be decoded. No read model will update
            until it is repaired; see the API log.
          </p>
        )}
        {held.map((entry) => (
          <p key={entry.projection}>
            {entry.projection} is stuck at event #{entry.global_nonce} ({entry.event_type}) and will not update
            until it is fixed; see the API log.
          </p>
        ))}
      </div>
    </div>
  )
}

export function ReadPathBanner({ health }: { health: ReadPathHealth }) {
  const stuck = health.held.length > 0 || health.haltedAt !== null
  if (!stuck && health.rebuilding.length === 0) return null
  return (
    <div className="mb-4 space-y-2">
      {stuck && <StuckBanner held={health.held} haltedAt={health.haltedAt} />}
      {health.rebuilding.length > 0 && <RebuildingBanner rebuilding={health.rebuilding} />}
    </div>
  )
}

/** A page's inline note that ITS read model is rebuilding, so a short list says why. */
export function ReadModelNotice({ status }: { status: ReadModelStatus | null }) {
  if (!status?.rebuilding) return null
  return (
    <p
      role="status"
      data-testid="read-model-notice"
      className="rounded-md border border-blue-500/20 bg-blue-500/5 px-3 py-2 text-xs text-blue-300"
    >
      This page may be incomplete while {status.label_display} is rebuilt ({status.progress_display},{' '}
      {status.events_behind_display}). The most recent entries may be missing until it catches up.
    </p>
  )
}
