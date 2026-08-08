/**
 * Agent-provider label vocabulary - the single source for "which agent" names.
 *
 * Keyed by the domain provider value (syn_shared/agents.py AgentProvider).
 * Kept separate from AgentBadge.tsx so the component file exports only a
 * component (react-refresh/only-export-components).
 */

// Keep in sync with AgentProvider in packages/syn-shared/src/syn_shared/agents.py.
export const AGENT_PROVIDER_LABELS: Record<string, string> = {
  claude: 'Claude',
  'claude-interactive': 'Claude (interactive)',
  codex: 'Codex',
}

export function agentProviderLabel(provider: string | null): string | null {
  if (!provider) return null
  return AGENT_PROVIDER_LABELS[provider.toLowerCase()] ?? provider
}
