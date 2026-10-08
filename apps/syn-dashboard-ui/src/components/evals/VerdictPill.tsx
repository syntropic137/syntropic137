import type { EvalVerdict } from '../../api/evals'
import { verdictColour } from '../../utils/evalVerdict'

/** A run's verdict, or "Unscored" when no scorer has judged it yet. */
export function VerdictPill({ verdict }: { verdict: EvalVerdict | null }) {
  const colour = verdictColour(verdict)
  return (
    <span
      data-verdict={verdict ?? 'UNSCORED'}
      className="inline-flex items-center whitespace-nowrap rounded-full px-2 py-0.5 text-xs font-medium"
      style={{ color: colour, backgroundColor: `${colour}22` }}
    >
      {verdict ?? 'Unscored'}
    </span>
  )
}
