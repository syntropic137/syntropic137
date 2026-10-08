import { Link } from 'react-router-dom'

import type { EvalRun } from '../../api/evals'
import { formatTimestampLocale } from '../../utils/dateFormatters'
import { formatScore } from '../../utils/evalVerdict'
import { VerdictPill } from './VerdictPill'

function RunEvidence({ run }: { run: EvalRun }) {
  if (!run.evidence_excerpt) return null
  return (
    <details className="mt-1 text-xs text-[var(--color-text-secondary)]">
      <summary className="cursor-pointer text-[var(--color-text-muted)]">
        Evidence{run.scorer ? ` · ${run.scorer}` : ''}
      </summary>
      <p className="mt-1 whitespace-pre-wrap break-words">{run.evidence_excerpt}</p>
    </details>
  )
}

/** Every run of an eval, newest first, each linking to its execution. */
export function EvalRunsTable({ runs }: { runs: readonly EvalRun[] }) {
  if (runs.length === 0) {
    return <p className="p-4 text-sm text-[var(--color-text-muted)]">No runs yet.</p>
  }
  return (
    <table className="w-full table-fixed text-sm">
      <thead>
        <tr className="border-b border-[var(--color-border)] text-left text-xs text-[var(--color-text-muted)]">
          <th className="w-[55%] px-3 py-2 font-medium sm:w-auto">Run</th>
          <th className="hidden px-3 py-2 font-medium md:table-cell">Models</th>
          <th className="px-3 py-2 font-medium">Verdict</th>
          <th className="hidden px-3 py-2 text-right font-medium sm:table-cell">Cost</th>
          <th className="hidden px-3 py-2 text-right font-medium sm:table-cell">Duration</th>
        </tr>
      </thead>
      <tbody>
        {runs.map((run) => (
          <tr key={run.execution_id} className="border-b border-[var(--color-border)] align-top last:border-0">
            <td className="min-w-0 px-3 py-2">
              <Link
                to={`/executions/${run.execution_id}`}
                className="text-[var(--color-accent)] hover:underline"
                title={run.execution_id}
              >
                {formatTimestampLocale(run.started_at)}
              </Link>
              <div className="break-all text-xs text-[var(--color-text-muted)]">
                {run.workflow_id}
                {run.workflow_version && ` @ ${run.workflow_version}`}
              </div>
              {run.models.length > 0 && (
                <div className="break-all text-xs text-[var(--color-text-muted)] md:hidden">
                  {run.models.map((m) => `${m.phase_id}: ${m.model}`).join(' · ')}
                </div>
              )}
              <RunEvidence run={run} />
            </td>
            <td className="hidden break-all px-3 py-2 text-xs text-[var(--color-text-secondary)] md:table-cell">
              {run.models.length === 0
                ? '—'
                : run.models.map((m) => (
                    <div key={m.phase_id}>
                      <span className="text-[var(--color-text-muted)]">{m.phase_id}:</span> {m.model}
                    </div>
                  ))}
            </td>
            <td className="px-3 py-2">
              <VerdictPill verdict={run.verdict} />
              {run.score !== null && (
                <div className="mt-0.5 text-xs tabular-nums text-[var(--color-text-muted)]">{formatScore(run.score)}</div>
              )}
            </td>
            <td className="hidden px-3 py-2 text-right tabular-nums text-[var(--color-text-secondary)] sm:table-cell">
              {run.total_cost_display}
            </td>
            <td className="hidden px-3 py-2 text-right tabular-nums text-[var(--color-text-secondary)] sm:table-cell">
              {run.duration_display}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}
