import type { RuleClause } from '@syn137/skyline-core/patterns'
import type { HTMLAttributes } from 'svelte/elements'

export interface RuleSentenceProps extends Omit<HTMLAttributes<HTMLDivElement>, 'children'> {
  /** Build with buildRuleClauses() from a trigger. */
  clauses: readonly RuleClause[]
  /** `compact`: the CompPatterns sheet size (in lists). `full`: the trigger detail panel with dividers. */
  size?: 'compact' | 'full'
}
