/** Example states of the Harness Chip for /dev/patterns: the Landing board's chips. */
import type { HarnessChipProps } from '@syn137/skyline-core/patterns'

export const HARNESS_CHIP_EXAMPLES: readonly HarnessChipProps[] = [
  { provider: 'claude' },
  { provider: 'codex' },
  { provider: 'claude', label: 'implement · claude' },
  { provider: 'codex', label: 'review · codex' },
  { provider: 'claude', label: 'claude-sonnet-5-5' },
  { provider: 'codex', label: 'gpt-5.6-sol' },
  { provider: 'gemini', label: 'unknown harness' },
]
