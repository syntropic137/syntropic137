/**
 * Tokens split into what went IN to the model and what came OUT of it.
 *
 * Cache writes (`cache_creation_tokens`) are prompt tokens the provider stored
 * as it read them, billed on the input side; they were once listed under Out,
 * so every phase card disagreed with the execution header, whose "In" figure
 * already counts fresh + cache write + cache read. In = those three; Out =
 * generated output only.
 *
 * One component for the phase cards, the execution cost summary and the
 * session cost card, so the grouping cannot drift between them again.
 */

import { formatTokens } from '../utils/formatters'

export interface TokenInOutProps {
  /** Uncached prompt tokens (`input_tokens`). */
  fresh: number
  /** `cache_creation_tokens`. */
  cacheWrite: number
  /** `cache_read_tokens`. */
  cacheRead: number
  /** Generated tokens (`output_tokens`). */
  output: number
  /**
   * `compact` stacks the segments with exact counts, for narrow phase cards;
   * `card` sets them side by side with abbreviated counts.
   */
  variant?: 'compact' | 'card'
}

interface SegmentRow {
  label: string
  value: number
  color?: string
}

const STYLES = {
  compact: {
    container: 'space-y-1.5',
    segment: 'rounded-md',
    header: 'px-2 py-1',
    headerLabel: 'font-medium',
    headerTotal: 'text-[var(--color-text-secondary)]',
    body: 'px-2 py-1 space-y-0.5',
    format: (n: number) => n.toLocaleString(),
  },
  card: {
    container: 'grid grid-cols-2 gap-2',
    segment: 'rounded-lg',
    header: 'px-3 py-1.5',
    headerLabel: 'text-xs font-medium',
    headerTotal: 'text-sm font-semibold text-[var(--color-text-primary)]',
    body: 'px-3 py-1.5 space-y-0.5 text-xs',
    format: formatTokens,
  },
} as const

function Segment({ label, rows, accentColor, variant }: {
  label: string
  rows: SegmentRow[]
  accentColor: string
  variant: keyof typeof STYLES
}) {
  const style = STYLES[variant]
  const total = rows.reduce((sum, r) => sum + r.value, 0)
  return (
    <div className={`${style.segment} border border-[var(--color-border)] overflow-hidden`} data-testid={`token-segment-${label.toLowerCase()}`}>
      <div className={`flex items-center justify-between ${style.header} ${accentColor}`}>
        <span className={style.headerLabel}>{label}</span>
        <span className={style.headerTotal} data-testid="token-segment-total">{style.format(total)}</span>
      </div>
      <div className={style.body}>
        {rows.map((r) => (
          <div key={r.label} className="flex justify-between">
            <span className={r.color ?? 'text-[var(--color-text-muted)]'}>{r.label}</span>
            <span className={r.color ?? 'text-[var(--color-text-secondary)]'}>{style.format(r.value)}</span>
          </div>
        ))}
      </div>
    </div>
  )
}

export function TokenInOut({ fresh, cacheWrite, cacheRead, output, variant = 'card' }: TokenInOutProps) {
  return (
    <div className={STYLES[variant].container}>
      <Segment
        label="In"
        variant={variant}
        accentColor="bg-indigo-500/10 text-indigo-400"
        rows={[
          { label: 'Fresh', value: fresh },
          { label: 'Cache write', value: cacheWrite, color: 'text-amber-400' },
          { label: 'Cache read', value: cacheRead, color: 'text-emerald-400' },
        ]}
      />
      <Segment
        label="Out"
        variant={variant}
        accentColor="bg-violet-500/10 text-violet-400"
        rows={[{ label: 'Output', value: output }]}
      />
    </div>
  )
}
