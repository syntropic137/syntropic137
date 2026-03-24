import type { HeatmapDayBucket } from '../types'

export function formatCompact(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`
  return n.toLocaleString()
}

export interface TooltipData {
  day: string
  bucket: HeatmapDayBucket | undefined
}

export function HeatmapTooltip({ data }: { data: TooltipData }) {
  const { day, bucket } = data

  const date = new Date(day + 'T00:00:00')
  const formatted = date.toLocaleDateString('en-US', {
    weekday: 'short',
    month: 'short',
    day: 'numeric',
    year: 'numeric',
  })

  if (!bucket || bucket.count === 0) {
    return (
      <div
        className="glass-panel"
        style={{
          padding: '10px 14px',
          fontSize: 12,
          background: 'rgba(22, 22, 37, 0.97)',
          border: '1px solid var(--color-border)',
          pointerEvents: 'none',
          minWidth: 200,
        }}
      >
        <div className="font-medium" style={{ color: 'var(--color-text-primary)', marginBottom: 4 }}>
          {formatted}
        </div>
        <div style={{ color: 'var(--color-text-muted)' }}>No activity</div>
      </div>
    )
  }

  const b = bucket.breakdown

  return (
    <div
      className="glass-panel"
      style={{
        padding: '12px 16px',
        fontSize: 12,
        background: 'rgba(22, 22, 37, 0.97)',
        border: '1px solid var(--color-border)',
        pointerEvents: 'none',
        minWidth: 240,
        maxWidth: 320,
      }}
    >
      <div className="font-medium" style={{ color: 'var(--color-text-primary)', marginBottom: 8, fontSize: 13 }}>
        {formatted}
      </div>

      <div style={{ display: 'flex', gap: 16, marginBottom: 8 }}>
        <TooltipStat label="Sessions" value={String(b.sessions)} highlight />
        <TooltipStat label="Executions" value={String(b.executions)} />
        <TooltipStat label="Commits" value={String(b.commits)} />
      </div>

      <div style={{ borderTop: '1px solid rgba(77, 128, 255, 0.1)', margin: '6px 0' }} />

      <div style={{ color: 'var(--color-text-secondary)', lineHeight: 1.7 }}>
        <div style={{ color: 'var(--color-text-muted)', fontSize: 10, textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: 2 }}>
          Tokens
        </div>
        <TooltipRow label="Input" value={formatCompact(b.input_tokens)} />
        <TooltipRow label="Output" value={formatCompact(b.output_tokens)} />
        <TooltipRow label="Cache create" value={formatCompact(b.cache_creation_tokens)} />
        <TooltipRow label="Cache read" value={formatCompact(b.cache_read_tokens)} />
      </div>

      <div style={{ borderTop: '1px solid rgba(77, 128, 255, 0.1)', margin: '6px 0' }} />

      <div style={{ display: 'flex', justifyContent: 'space-between' }}>
        <span style={{ color: 'var(--color-text-muted)' }}>Cost</span>
        <span className="font-mono" style={{ color: 'var(--color-success)', fontWeight: 600 }}>
          ${b.cost_usd.toFixed(2)}
        </span>
      </div>
    </div>
  )
}

function TooltipStat({ label, value, highlight }: { label: string; value: string; highlight?: boolean }) {
  return (
    <div style={{ textAlign: 'center' }}>
      <div
        className="font-mono"
        style={{
          fontSize: 16,
          fontWeight: 600,
          color: highlight ? 'var(--color-accent-primary)' : 'var(--color-text-primary)',
        }}
      >
        {value}
      </div>
      <div style={{ fontSize: 10, color: 'var(--color-text-muted)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
        {label}
      </div>
    </div>
  )
}

function TooltipRow({ label, value }: { label: string; value: string }) {
  return (
    <div style={{ display: 'flex', justifyContent: 'space-between', gap: 16 }}>
      <span style={{ color: 'var(--color-text-muted)' }}>{label}</span>
      <span className="font-mono" style={{ color: 'var(--color-text-primary)' }}>{value}</span>
    </div>
  )
}
