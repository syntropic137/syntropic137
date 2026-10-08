/**
 * Runs over time: x is when a run started, one lane per variant, and each
 * marker is coloured by its verdict. Drawn by hand in SVG (no chart library):
 * the shape is a dot plot, and a viewBox scales it to any width, 375px included.
 */

import type { EvalRun } from '../../api/evals'
import { UNSCORED_COLOUR, VERDICT_COLOURS, runVariantKey, verdictColour } from '../../utils/evalVerdict'

const WIDTH = 600
const PAD_X = 12
const LANE_HEIGHT = 34
const LABEL_HEIGHT = 12
const AXIS_HEIGHT = 18
const MAX_LABEL_CHARS = 80

function truncate(text: string): string {
  return text.length > MAX_LABEL_CHARS ? `${text.slice(0, MAX_LABEL_CHARS - 1)}…` : text
}

function shortDate(ms: number): string {
  return new Date(ms).toLocaleDateString(undefined, { month: 'short', day: 'numeric' })
}

export function EvalRunsChart({ runs }: { runs: readonly EvalRun[] }) {
  const dated = runs.filter((r) => r.started_at && !Number.isNaN(Date.parse(r.started_at)))
  if (dated.length === 0) {
    return <p className="p-4 text-sm text-[var(--color-text-muted)]">No runs yet. A run appears here once it starts.</p>
  }

  const lanes = [...new Set(dated.map(runVariantKey))].sort()
  const times = dated.map((r) => Date.parse(r.started_at as string))
  const min = Math.min(...times)
  const max = Math.max(...times)
  // A single instant has no span to spread over: centre it.
  const x = (t: number) => (max === min ? WIDTH / 2 : PAD_X + ((t - min) / (max - min)) * (WIDTH - 2 * PAD_X))
  const height = lanes.length * LANE_HEIGHT + AXIS_HEIGHT

  return (
    <div className="p-4">
      <svg
        role="img"
        aria-label={`${dated.length} runs over time across ${lanes.length} variants`}
        viewBox={`0 0 ${WIDTH} ${height}`}
        className="block h-auto w-full"
      >
        {lanes.map((lane, i) => {
          const y = i * LANE_HEIGHT + LABEL_HEIGHT + 10
          return (
            <g key={lane} data-lane={lane}>
              <text x={PAD_X} y={i * LANE_HEIGHT + LABEL_HEIGHT} fontSize={11} fill="var(--color-text-muted)">
                {truncate(lane)}
              </text>
              <line x1={PAD_X} x2={WIDTH - PAD_X} y1={y} y2={y} stroke="var(--color-border)" />
            </g>
          )
        })}
        {dated.map((run) => {
          const lane = lanes.indexOf(runVariantKey(run))
          return (
            <circle
              key={run.execution_id}
              data-verdict={run.verdict ?? 'UNSCORED'}
              cx={x(Date.parse(run.started_at as string))}
              cy={lane * LANE_HEIGHT + LABEL_HEIGHT + 10}
              r={5}
              fill={verdictColour(run.verdict)}
              stroke="var(--color-surface)"
              strokeWidth={1.5}
            >
              <title>{`${run.started_at} · ${run.verdict ?? 'Unscored'} · ${run.execution_id}`}</title>
            </circle>
          )
        })}
        <text x={PAD_X} y={height - 4} fontSize={11} fill="var(--color-text-muted)">
          {shortDate(min)}
        </text>
        {max !== min && (
          <text x={WIDTH - PAD_X} y={height - 4} fontSize={11} textAnchor="end" fill="var(--color-text-muted)">
            {shortDate(max)}
          </text>
        )}
      </svg>
      <ul className="mt-2 flex flex-wrap gap-3 text-xs text-[var(--color-text-secondary)]" aria-label="Verdict legend">
        {[...Object.entries(VERDICT_COLOURS), ['Unscored', UNSCORED_COLOUR] as const].map(([label, colour]) => (
          <li key={label} className="inline-flex items-center gap-1">
            <span className="inline-block h-2.5 w-2.5 rounded-full" style={{ backgroundColor: colour }} />
            {label}
          </li>
        ))}
      </ul>
    </div>
  )
}
