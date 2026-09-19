/**
 * Slim progress bar with a "completed/total" label, used in the Executions
 * table's Progress column. Moved out of executionColumns.tsx so the column
 * file exports only column defs (react-refresh/only-export-components).
 */

import { clsx } from 'clsx'
import type { ExecutionListItem } from '../../types'
import { REFUSED, outcomeTone } from '../../utils/executionOutcome'

export function ExecutionProgressBar({ exec }: { exec: ExecutionListItem }) {
  const pct = exec.total_phases > 0 ? (exec.completed_phases / exec.total_phases) * 100 : 0
  // Coloured by outcome rather than by status: a correct refusal is amber
  // here for the same reason its badge is, and the bar and the badge sit in
  // the same row, so a bar that decided for itself would contradict the badge
  // beside it (#1367).
  const tone = outcomeTone(exec.status, exec.failure_classification)
  return (
    <div className="flex items-center gap-2">
      <div className="h-2 w-20 overflow-hidden rounded-full bg-[var(--color-surface-elevated)]">
        <div
          className={clsx(
            'h-full rounded-full transition-all',
            tone === 'completed' && 'bg-emerald-500',
            tone === 'failed' && 'bg-red-500',
            tone === REFUSED && 'bg-amber-500',
            tone === 'running' && 'bg-blue-500',
            tone === 'pending' && 'bg-slate-500',
            tone === 'cancelled' && 'bg-slate-400',
          )}
          style={{ width: `${pct}%` }}
        />
      </div>
      <span className="text-xs text-[var(--color-text-muted)]">
        {exec.completed_phases}/{exec.total_phases}
      </span>
    </div>
  )
}
