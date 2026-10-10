import type { AgentPromptSpec } from '@syn137/skyline-core/patterns'
import type { HTMLAttributes } from 'svelte/elements'

export interface AgentPromptButtonProps extends Omit<HTMLAttributes<HTMLDivElement>, 'children'> {
  /** The prompt to copy, or a spec that buildAgentPrompt() turns into one. */
  prompt: string | AgentPromptSpec
  label?: string
  copiedLabel?: string
  /** Line beside the button before and after copying. */
  hint?: string
  copiedHint?: string
  oncopied?: (prompt: string) => void
}
