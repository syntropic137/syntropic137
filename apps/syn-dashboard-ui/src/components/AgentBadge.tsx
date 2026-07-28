/**
 * Compact badge naming the agent that ran a session/phase.
 *
 * Answers "which agent" (Claude vs Codex), distinct from the workspace image.
 * Sourced from the domain `agent_provider` value. Shared by the session detail
 * header, the sessions table, and the mobile session card. Label vocabulary
 * lives in ./agentProvider.
 */

import { Bot } from 'lucide-react'

import { agentProviderLabel } from './agentProvider'

export function AgentBadge({
  provider,
  className = '',
}: {
  provider: string | null
  className?: string
}) {
  const label = agentProviderLabel(provider)
  if (!label) return null
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full bg-[var(--color-accent)]/15 px-2 py-0.5 text-xs font-medium text-[var(--color-accent)] ${className}`}
    >
      <Bot className="h-3 w-3" />
      {label}
    </span>
  )
}
