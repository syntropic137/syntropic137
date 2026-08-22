// Agent providers a workflow phase can declare. Mirrors the backend
// AgentProvider StrEnum (packages/syn-shared/src/syn_shared/agents.py).
// Kept as one source of truth so no provider string is hard-coded elsewhere.

export const AGENT_PROVIDER = {
  CLAUDE: 'claude',
  CODEX: 'codex',
} as const

export type AgentProvider = (typeof AGENT_PROVIDER)[keyof typeof AGENT_PROVIDER]

export interface ProviderOption {
  value: AgentProvider
  label: string
}

export const PROVIDER_OPTIONS: readonly ProviderOption[] = [
  { value: AGENT_PROVIDER.CLAUDE, label: 'Claude' },
  { value: AGENT_PROVIDER.CODEX, label: 'Codex' },
]

// Codex uses its account-default model; a Claude model id (e.g. "haiku") is
// rejected by codex, so the phase editor hides the model field for codex and
// never sends a model override for it.
export function providerUsesModelField(provider: string): boolean {
  return provider !== AGENT_PROVIDER.CODEX
}

// Human-facing label for a provider value; falls back to the raw value or a
// default when a phase predates provider tracking.
export function providerLabel(provider: string | null | undefined): string {
  if (!provider) return 'Claude'
  const match = PROVIDER_OPTIONS.find((o) => o.value === provider)
  return match ? match.label : provider
}
