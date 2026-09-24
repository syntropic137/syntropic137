/**
 * The model that ran, as the API displays it, plus optional requested context.
 *
 * `display` is an API `*_display` field (e.g. "claude-opus-5-5" or
 * "unknown (requested: gpt-sol)") and is rendered verbatim. The secondary line
 * names the requested alias only when a different model was observed.
 */

import { requestedModelNote } from '../utils/modelLabels'

export function ObservedModel({
  display,
  observed,
  requested,
  className = '',
}: {
  display: string | null | undefined
  observed: string | null | undefined
  requested: string | null | undefined
  className?: string
}) {
  if (!display) return null
  const note = requestedModelNote(observed, requested)
  return (
    <span className={`inline-flex flex-col ${className}`} data-testid="observed-model">
      <span className="font-mono">{display}</span>
      {note && <span className="text-[var(--color-text-muted)]">{note}</span>}
    </span>
  )
}
