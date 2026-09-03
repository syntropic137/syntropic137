/**
 * Compact badge naming what ran a session/phase: the agent AND the model.
 *
 * Both halves, because neither answers the question alone. "Claude" does not
 * say whether a reasoning session quietly ran on sonnet, and a bare "Opus 4.5"
 * does not say which harness launched it. Showing only the provider is what
 * issue #1094 reported: the model was on the wire, and every session surface
 * dropped it.
 *
 * One component for the sessions table, the mobile session card and the
 * session detail header, so the three cannot disagree about what "what ran"
 * means. Labels come from ./agentProvider; the model string is already
 * rendered server-side (`agent_model_display`) and is passed through as-is.
 */

import { Bot } from 'lucide-react'

import { agentProviderAccent, agentProviderLabel } from './agentProvider'

const sizeClasses = {
  sm: 'gap-1.5 px-2 py-0.5 text-xs',
  lg: 'gap-1.5 px-3 py-1 text-sm',
}

const iconClasses = {
  sm: 'h-3 w-3',
  lg: 'h-4 w-4',
}

export function AgentBadge({
  provider,
  modelDisplay = null,
  size = 'sm',
  className = '',
}: {
  provider: string | null
  modelDisplay?: string | null
  size?: 'sm' | 'lg'
  className?: string
}) {
  const label = [agentProviderLabel(provider), modelDisplay].filter(Boolean).join(' / ')
  if (!label) return null
  const accent = agentProviderAccent(provider)
  return (
    <span
      className={`inline-flex items-center rounded-full font-medium ${sizeClasses[size]} ${className}`}
      style={{ color: accent, backgroundColor: `color-mix(in srgb, ${accent} 15%, transparent)` }}
    >
      <Bot className={iconClasses[size]} />
      {label}
    </span>
  )
}
