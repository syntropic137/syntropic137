/** Example states of the Harness Lanes for /dev/patterns: the Landing board's plan-implement-review workflow. */
import type { HarnessLanesProps } from '@syn137/skyline-core/patterns'

export const HARNESS_LANES_EXAMPLES: readonly HarnessLanesProps[] = [
  {
    label: 'plan-implement-review: one workflow, two vendors',
    phases: [
      { name: 'plan', provider: 'claude', span: 2 },
      { name: 'implement', provider: 'codex', span: 3 },
      { name: 'fix', provider: 'claude', span: 2 },
      { name: 'review', provider: 'codex', span: 2 },
    ],
  },
  {
    label: 'implement-and-review',
    phases: [
      { name: 'implement', provider: 'claude', span: 3 },
      { name: 'review', provider: 'codex', span: 2 },
    ],
  },
]
