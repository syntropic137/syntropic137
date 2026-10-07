import type { EvalVariant } from '../../api/evals'
import { formatRelativeTime } from '../../utils/dateFormatters'

/**
 * The Compare table: one row per (workflow, observed models) variant, so the
 * same eval run by different workflows and models can be read side by side.
 */
export function EvalVariantsTable({ variants }: { variants: readonly EvalVariant[] }) {
  if (variants.length === 0) {
    return <p className="p-4 text-sm text-[var(--color-text-muted)]">No runs yet, so nothing to compare.</p>
  }
  return (
    <table className="w-full table-fixed text-sm">
      <thead>
        <tr className="border-b border-[var(--color-border)] text-left text-xs text-[var(--color-text-muted)]">
          <th className="w-[45%] px-3 py-2 font-medium sm:w-auto">Workflow · models</th>
          <th className="px-3 py-2 text-right font-medium">Runs</th>
          <th className="px-3 py-2 text-right font-medium">Pass rate</th>
          <th className="hidden px-3 py-2 text-right font-medium sm:table-cell">Avg cost</th>
          <th className="hidden px-3 py-2 text-right font-medium sm:table-cell">Last run</th>
        </tr>
      </thead>
      <tbody>
        {variants.map((v) => (
          <tr key={`${v.workflow_id}|${v.models.join(',')}`} className="border-b border-[var(--color-border)] last:border-0">
            <td className="break-all px-3 py-2">
              <div className="text-[var(--color-text-primary)]">{v.workflow_id}</div>
              <div className="text-xs text-[var(--color-text-muted)]">
                {v.models.length ? v.models.join(', ') : 'no model reported'}
              </div>
            </td>
            <td className="px-3 py-2 text-right tabular-nums text-[var(--color-text-secondary)]">
              {v.pass_count}/{v.run_count}
            </td>
            <td className="px-3 py-2 text-right tabular-nums text-[var(--color-text-primary)]">{v.pass_rate_display}</td>
            <td className="hidden px-3 py-2 text-right tabular-nums text-[var(--color-text-secondary)] sm:table-cell">
              {v.avg_cost_display}
            </td>
            <td
              className="hidden px-3 py-2 text-right text-[var(--color-text-secondary)] sm:table-cell"
              title={v.last_run_at ?? undefined}
            >
              {formatRelativeTime(v.last_run_at)}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}

/** The same comparison squeezed into one line per variant, for the eval list. */
export function EvalVariantsStrip({ variants }: { variants: readonly EvalVariant[] }) {
  if (variants.length === 0) return null
  return (
    <ul className="flex flex-wrap gap-1.5" aria-label="Variants">
      {variants.map((v) => (
        <li
          key={`${v.workflow_id}|${v.models.join(',')}`}
          className="min-w-0 max-w-full break-all rounded bg-[var(--color-surface-elevated)] px-1.5 py-0.5 text-[11px] text-[var(--color-text-secondary)]"
        >
          {v.workflow_id}
          {v.models.length > 0 && <span className="text-[var(--color-text-muted)]"> · {v.models.join(', ')}</span>}
          {' → '}
          <span className="text-[var(--color-text-primary)]">{v.pass_rate_display}</span>
        </li>
      ))}
    </ul>
  )
}
