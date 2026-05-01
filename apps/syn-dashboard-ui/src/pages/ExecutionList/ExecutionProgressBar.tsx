/**
 * Slim progress bar with a "completed/total" label, used in the Executions
 * table's Progress column. Moved out of executionColumns.tsx so the column
 * file exports only column defs (react-refresh/only-export-components).
 */

import { clsx } from 'clsx'
import type { ExecutionListItem } from '../../types'

export function ExecutionProgressBar({ exec }: { exec: ExecutionListItem }) {
  const pct = exec.total_phases > 0 ? (exec.completed_phases / exec.total_phases) * 100 : 0
  return (
    <div className="flex items-center gap-2">
      <div className="h-2 w-20 overflow-hidden rounded-full bg-[var(--color-surface-elevated)]">
        <div
          className={clsx(
            'h-full rounded-full transition-all',
            exec.status === 'completed' && 'bg-emerald-500',
            exec.status === 'failed' && 'bg-red-500',
            exec.status === 'running' && 'bg-blue-500',
            exec.status === 'pending' && 'bg-slate-500',
            exec.status === 'cancelled' && 'bg-slate-400',
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
