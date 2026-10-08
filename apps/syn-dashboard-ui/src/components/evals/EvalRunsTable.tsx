import { Link } from 'react-router-dom'

import type { EvalRun } from '../../api/evals'
import { formatTimestampLocale } from '../../utils/dateFormatters'
import { formatScore } from '../../utils/evalVerdict'
import { VerdictPill } from './VerdictPill'

function RunEvidence({ run }: { run: EvalRun }) {
  if (!run.evidence_excerpt) return <span className="text-[var(--color-text-muted)]">—</span>
  return (
    <details className="text-xs text-[var(--color-text-secondary)]">
      <summary className="cursor-pointer truncate text-[var(--color-text-muted)]">{run.evidence_excerpt}</summary>
      <p className="mt-1 whitespace-pre-wrap break-words">{run.evidence_excerpt}</p>
    </details>
  )
}

function RunRow({ run }: { run: EvalRun }) {
  const num = 'px-3 py-2 text-right tabular-nums text-[var(--color-text-secondary)]'
  return (
    <tr className="border-b border-[var(--color-border)] align-top last:border-0">
      <td className="px-3 py-2">
        <Link to={`/executions/${run.execution_id}`} className="text-[var(--color-accent)] hover:underline" title={run.execution_id}>
          {formatTimestampLocale(run.started_at)}
        </Link>
      </td>
      <td className="break-all px-3 py-2 text-xs text-[var(--color-text-secondary)]">
        {run.workflow_id}
        {run.workflow_version && <span className="text-[var(--color-text-muted)]"> @ {run.workflow_version}</span>}
        {run.models.map((m) => (
          <div key={`${m.phase_id}|${m.model}`} className="text-[var(--color-text-muted)]">
            {m.phase_id}: {m.model}
          </div>
        ))}
      </td>
      <td className="px-3 py-2">
        <VerdictPill verdict={run.verdict} />
      </td>
      <td className={num}>{run.score === null ? '—' : formatScore(run.score)}</td>
      <td className={num}>{run.duration_display}</td>
      <td className={num}>{run.total_cost_display}</td>
      <td className="break-all px-3 py-2 text-xs text-[var(--color-text-secondary)]">
        {run.scorer ? `${run.scorer}${run.scorer_version ? ` v${run.scorer_version}` : ''}` : '—'}
      </td>
      <td className="min-w-0 px-3 py-2">
        <RunEvidence run={run} />
      </td>
    </tr>
  )
}

const HEADERS: [string, string][] = [
  ['Date', 'w-[9rem]'],
  ['Variant', 'w-[13rem]'],
  ['Verdict', 'w-[6rem]'],
  ['Score', 'w-[4.5rem] text-right'],
  ['Duration', 'w-[6rem] text-right'],
  ['Cost', 'w-[6rem] text-right'],
  ['Scorer', 'w-[8rem]'],
  ['Evidence', 'w-[16rem]'],
]

/**
 * A page of an eval's runs, newest first, each linking to its execution.
 * Every column shows at every width: on a narrow screen the table scrolls
 * inside its own container instead of dropping duration and cost.
 */
export function EvalRunsTable({ runs }: { runs: readonly EvalRun[] }) {
  if (runs.length === 0) {
    return <p className="p-4 text-sm text-[var(--color-text-muted)]">No runs yet.</p>
  }
  return (
    <div className="overflow-x-auto" data-testid="runs-scroll">
      <table className="w-full min-w-[60rem] table-fixed text-sm">
        <thead>
          <tr className="border-b border-[var(--color-border)] text-left text-xs text-[var(--color-text-muted)]">
            {HEADERS.map(([label, width]) => (
              <th key={label} className={`px-3 py-2 font-medium ${width}`}>
                {label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {runs.map((run) => (
            <RunRow key={run.execution_id} run={run} />
          ))}
        </tbody>
      </table>
    </div>
  )
}
