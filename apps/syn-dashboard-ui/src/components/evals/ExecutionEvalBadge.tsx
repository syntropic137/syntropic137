import { FlaskConical } from 'lucide-react'
import { Link } from 'react-router-dom'

import type { ExecutionEvalRun } from '../../api/evals'
import { VerdictPill } from './VerdictPill'

/**
 * An execution's Eval badge, on its page and on its row in the Executions
 * list: which eval this run is a data point of, linked to it, with the run's
 * current verdict ("Unscored" until a scorer records one). Renders nothing for an execution in no eval.
 *
 * Read from the `eval` of `GET /executions/{id}` or of a `GET /executions`
 * row: one shape, derived from the same membership the eval's runs table
 * lists, so none of them can disagree. The name truncates, so the badge fits
 * whatever width its container gives it.
 */
export function ExecutionEvalBadge({ evalRun }: { evalRun: ExecutionEvalRun | null | undefined }) {
  if (!evalRun) return null
  const label = evalRun.eval_name ?? evalRun.eval_id
  return (
    <Link
      to={`/evals/${encodeURIComponent(evalRun.eval_id)}`}
      data-testid="execution-eval-badge"
      title={`Run of eval ${evalRun.eval_id} (${evalRun.association_kind})`}
      className="inline-flex min-w-0 max-w-full items-center gap-2 rounded-full border border-[var(--color-border)] bg-[var(--color-surface-elevated)] px-2.5 py-1 text-xs text-[var(--color-text-secondary)] hover:border-[var(--color-accent)] hover:text-[var(--color-text-primary)]"
    >
      <FlaskConical className="h-3.5 w-3.5 shrink-0" aria-hidden="true" />
      <span className="shrink-0 text-[var(--color-text-muted)]">Eval</span>
      <span className="min-w-0 truncate font-medium">{label}</span>
      {evalRun.association_kind === 'attached' && (
        <span className="shrink-0 text-[var(--color-text-muted)]">attached</span>
      )}
      <VerdictPill verdict={evalRun.verdict} />
    </Link>
  )
}
