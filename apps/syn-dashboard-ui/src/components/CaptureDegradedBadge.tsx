import { AlertTriangle } from 'lucide-react'

/**
 * "Capture degraded" on an execution or phase (#1516).
 *
 * The workspace started with the session store disabled because its doctor
 * failed, so transcripts from this run are not in the store. The text is the
 * server's `capture_status_display`, verbatim: it names the failed checks.
 * Renders nothing when the field is null, which is every healthy run and
 * every run with no session store configured.
 */
export function CaptureDegradedBadge({ display }: { display: string | null | undefined }) {
  if (!display) return null
  return (
    <span
      data-testid="capture-degraded"
      title="The session store was unreachable when the workspace started; this run's transcripts were not captured."
      className="inline-flex items-center gap-1 rounded-full border border-amber-500/30 bg-amber-500/10 px-2 py-0.5 text-xs font-medium text-amber-400"
    >
      <AlertTriangle className="h-3 w-3" />
      {display}
    </span>
  )
}
