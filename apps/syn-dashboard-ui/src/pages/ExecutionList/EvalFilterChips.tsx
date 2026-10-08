/**
 * "Evals only" / "Hide evals": the Executions list narrowed by eval membership.
 *
 * Two chips, at most one active; pressing the active one returns to every run.
 * The narrowing itself is the server's (`in_eval`), so the total and the
 * status counts beside these chips describe the same collection the rows do.
 */

import type { EvalFilter } from '../../api/executions'
import { FilterChip } from '../../components/FilterChip'

const CHIPS: { value: Exclude<EvalFilter, 'all'>; label: string }[] = [
  { value: 'only', label: 'Evals only' },
  { value: 'hide', label: 'Hide evals' },
]

export function EvalFilterChips({
  value,
  onChange,
}: {
  value: EvalFilter
  onChange: (next: EvalFilter) => void
}) {
  return (
    <div role="group" aria-label="Eval runs" className="flex flex-wrap items-center gap-2">
      {CHIPS.map((chip) => (
        <FilterChip
          key={chip.value}
          label={chip.label}
          isActive={value === chip.value}
          onClick={() => onChange(value === chip.value ? 'all' : chip.value)}
        />
      ))}
    </div>
  )
}
