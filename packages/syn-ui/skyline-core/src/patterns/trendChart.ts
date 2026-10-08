/**
 * Trend Chart and Trend Spark props (Eval and Workflows boards). Positions
 * are plot percentages from skyline-core/geometry/trend; `color` is a series
 * slot 1..4 that the component maps to --sky-color-series-N.
 */
import type { DurationTrendKind } from '../screens/workflows/trend'

export interface TrendLine {
  key: string
  color: number
  /** Path in the chart's viewBox (1000 x viewHeight). */
  d: string
}

export interface TrendDot {
  /** Run index, passed back to onpick. */
  i: number
  x: number
  /** Percent from the top of the plot. */
  top: number
  color: number
  label: string
}

export interface TrendEnd {
  key: string
  label: string
  color: number
  top: number
}

export interface TrendTick {
  /** Percent from the top (y ticks) or from the left (x ticks). */
  at: number
  label: string
}

export interface TrendNote {
  x: number
  label: string
}

export interface TrendChartProps {
  lines: readonly TrendLine[]
  dots: readonly TrendDot[]
  ends: readonly TrendEnd[]
  yTicks: readonly TrendTick[]
  xTicks?: readonly TrendTick[]
  notes?: readonly TrendNote[]
  /** Show the note labels above the plot (the top chart only). */
  noteLabels?: boolean
  /** Dashed threshold line, percent from the top. */
  threshold?: { top: number; label: string } | null
  /** viewBox height the line paths were drawn for. */
  viewHeight: number
  /** Selected run index: its dot grows. */
  selected?: number
  /** x percent of the selected run: a hairline marks it. */
  hair?: number | null
  /** Plot height: lg for the score chart, md for the one beneath. */
  size?: 'lg' | 'md'
  onpick?: (i: number) => void
}

export interface TrendSparkProps {
  kind: DurationTrendKind
  word: string
  sub: string
  label: string
  spark: string
}
