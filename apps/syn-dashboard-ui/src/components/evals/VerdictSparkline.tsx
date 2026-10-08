import type { EvalVerdict } from '../../api/evals'
import { verdictColour } from '../../utils/evalVerdict'

const BAR_WIDTH = 6
const GAP = 2
const HEIGHT = 16

/**
 * The latest verdicts, oldest left: a pass is a full bar, a fail a short one,
 * so the trend reads without colour; colour then says which is which.
 */
export function VerdictSparkline({ verdicts }: { verdicts: readonly (EvalVerdict | null)[] }) {
  if (verdicts.length === 0) return null
  const width = verdicts.length * (BAR_WIDTH + GAP) - GAP
  const counts = verdicts.reduce(
    (acc, v) => ({ ...acc, [v ?? 'unscored']: (acc[v ?? 'unscored'] ?? 0) + 1 }),
    {} as Record<string, number>,
  )
  const label = `Last ${verdicts.length} runs: ${Object.entries(counts)
    .map(([k, n]) => `${n} ${k}`)
    .join(', ')}`

  return (
    <svg role="img" aria-label={label} width={width} height={HEIGHT} viewBox={`0 0 ${width} ${HEIGHT}`} className="shrink-0">
      {verdicts.map((verdict, i) => {
        const h = verdict === 'PASS' ? HEIGHT : verdict === null ? 3 : HEIGHT / 2
        return (
          <rect
            key={i}
            data-verdict={verdict ?? 'UNSCORED'}
            x={i * (BAR_WIDTH + GAP)}
            y={HEIGHT - h}
            width={BAR_WIDTH}
            height={h}
            rx={1}
            fill={verdictColour(verdict)}
          />
        )
      })}
    </svg>
  )
}
