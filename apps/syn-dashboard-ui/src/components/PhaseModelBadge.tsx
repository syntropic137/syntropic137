/**
 * The model a phase DEFINITION asks for, and what that resolves to.
 *
 * Renders the API's `model_display` verbatim ("opus → claude-opus-5-5",
 * "gpt-sol → gpt-6-sol"), falling back to the raw `model` for a server that
 * sends no display. One component so the phase pipeline card and the phase
 * editor cannot drift into showing different things for the same phase.
 */

import { Cpu } from 'lucide-react'

export function PhaseModelBadge({
  model,
  modelDisplay,
}: {
  model: string | null | undefined
  modelDisplay: string | null | undefined
}) {
  const label = modelDisplay ?? model
  if (!label) return null
  return (
    <span
      className="inline-flex items-center gap-1 rounded-md bg-blue-500/15 px-2 py-0.5 text-xs text-blue-300 ring-1 ring-inset ring-blue-500/25"
      data-testid="phase-model-badge"
    >
      <Cpu className="h-3 w-3" />
      {label}
    </span>
  )
}
