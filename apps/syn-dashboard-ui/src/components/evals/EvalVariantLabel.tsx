import type { EvalVariant } from '../../api/evals'
import { judgedLabel, type VariantCounts } from '../../utils/evalVariants'
import { VerdictPill } from './VerdictPill'

/** Workflow @ version, the Best badge, observed models and last verdict: the same in the table and the cards. */
export function EvalVariantLabel({ v, best, counts }: { v: EvalVariant; best: boolean; counts: VariantCounts }) {
  return (
    <>
      <div className="text-[var(--color-text-primary)]">
        {v.workflow_id}
        {v.workflow_version && <span className="text-[var(--color-text-muted)]"> @ {v.workflow_version}</span>}
        {best && (
          <span className="ml-2 whitespace-nowrap rounded-full bg-emerald-500/15 px-1.5 py-0.5 text-[10px] font-medium text-emerald-400">
            Best · {judgedLabel(v, counts)}
          </span>
        )}
      </div>
      <div className="text-xs text-[var(--color-text-muted)]">{v.models.length ? v.models.join(', ') : 'no model reported'}</div>
      <div className="mt-1">
        <VerdictPill verdict={v.last_verdict} />
      </div>
    </>
  )
}
