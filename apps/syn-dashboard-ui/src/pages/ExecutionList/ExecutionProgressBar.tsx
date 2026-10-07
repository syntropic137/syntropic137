/**
 * Slim progress bar labelled with the API's phase progress, used in the Executions
 * table's Progress column. Moved out of executionColumns.tsx so the column
 * file exports only column defs (react-refresh/only-export-components).
 */

import { clsx } from 'clsx'
import type { ExecutionListItem } from '../../types'
import { REFUSED, TASK_FAILED, outcomeTone } from '../../utils/executionOutcome'

export function ExecutionProgressBar({ exec }: { exec: ExecutionListItem }) {
  // The API's progress, not completed/total: total counts the repair rounds a
  // certifying review skipped, so a finished run read "6/10" (PC-63).
  const progress = exec.phase_progress
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
            (tone === REFUSED || tone === TASK_FAILED) && 'bg-amber-500',
            tone === 'running' && 'bg-blue-500',
            tone === 'pending' && 'bg-slate-500',
            tone === 'cancelled' && 'bg-slate-400',
          )}
          style={{ width: `${progress.percent}%` }}
        />
      </div>
      <span className="text-xs text-[var(--color-text-muted)]">
        {progress.display}
      </span>
    </div>
  )
}
