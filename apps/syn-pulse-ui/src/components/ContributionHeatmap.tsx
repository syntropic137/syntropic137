import { useMemo, useState } from 'react'
import { ResponsiveCalendar } from '@nivo/calendar'
import type { HeatmapDayBucket } from '../types'

function formatCompact(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`
  return n.toLocaleString()
}

interface YearRange {
  from: string
  to: string
  label: string
}

function buildYearRanges(days: HeatmapDayBucket[]): YearRange[] {
  if (days.length === 0) return []
  const dates = days.map((d) => new Date(d.date))
  const minYear = Math.min(...dates.map((d) => d.getFullYear()))
  const maxYear = Math.max(...dates.map((d) => d.getFullYear()))
  const ranges: YearRange[] = []

  // Individual year ranges, newest first (like GitHub).
  // Jan 5 start avoids a Nivo ISO-week rendering quirk.
  for (let y = maxYear; y >= minYear; y--) {
    ranges.push({
      from: `${y}-01-05`,
      to: `${y}-12-31`,
      label: String(y),
    })
  }

  return ranges
}

interface TooltipData {
  day: string
  bucket: HeatmapDayBucket | undefined
}

function HeatmapTooltip({ data }: { data: TooltipData }) {
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

      {/* Activity counts */}
      <div style={{ display: 'flex', gap: 16, marginBottom: 8 }}>
        <TooltipStat label="Sessions" value={String(b.sessions)} highlight />
        <TooltipStat label="Executions" value={String(b.executions)} />
        <TooltipStat label="Commits" value={String(b.commits)} />
      </div>

      {/* Divider */}
      <div style={{ borderTop: '1px solid rgba(77, 128, 255, 0.1)', margin: '6px 0' }} />

      {/* Token breakdown */}
      <div style={{ color: 'var(--color-text-secondary)', lineHeight: 1.7 }}>
        <div style={{ color: 'var(--color-text-muted)', fontSize: 10, textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: 2 }}>
          Tokens
        </div>
        <TooltipRow label="Input" value={formatCompact(b.input_tokens)} />
        <TooltipRow label="Output" value={formatCompact(b.output_tokens)} />
        <TooltipRow label="Cache create" value={formatCompact(b.cache_creation_tokens)} />
        <TooltipRow label="Cache read" value={formatCompact(b.cache_read_tokens)} />
      </div>

      {/* Divider */}
      <div style={{ borderTop: '1px solid rgba(77, 128, 255, 0.1)', margin: '6px 0' }} />

      {/* Cost */}
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

/* ---------- Summary Stats ---------- */

interface SummaryStatsProps {
  days: HeatmapDayBucket[]
}

export function SummaryStats({ days }: SummaryStatsProps) {
  const totals = useMemo(() => {
    const t = {
      sessions: 0,
      executions: 0,
      commits: 0,
      cost_usd: 0,
      input_tokens: 0,
      output_tokens: 0,
      cache_creation_tokens: 0,
      cache_read_tokens: 0,
      active_days: 0,
    }
    for (const d of days) {
      if (d.count > 0) t.active_days++
      t.sessions += d.breakdown.sessions
      t.executions += d.breakdown.executions
      t.commits += d.breakdown.commits
      t.cost_usd += d.breakdown.cost_usd
      t.input_tokens += d.breakdown.input_tokens
      t.output_tokens += d.breakdown.output_tokens
      t.cache_creation_tokens += d.breakdown.cache_creation_tokens
      t.cache_read_tokens += d.breakdown.cache_read_tokens
    }
    return t
  }, [days])

  const totalTokens = totals.input_tokens + totals.output_tokens + totals.cache_creation_tokens + totals.cache_read_tokens

  // Current streak: consecutive days with activity ending today (or yesterday)
  const streak = useMemo(() => {
    const now = new Date()
    const today = now.toISOString().slice(0, 10)
    const yd = new Date(now)
    yd.setDate(yd.getDate() - 1)
    const yesterday = yd.toISOString().slice(0, 10)

    // Build a set of active dates
    const activeDates = new Set<string>()
    for (const d of days) {
      if (d.breakdown.sessions > 0) activeDates.add(d.date)
    }

    // Start from today or yesterday (whichever is active)
    let current: string
    if (activeDates.has(today)) {
      current = today
    } else if (activeDates.has(yesterday)) {
      current = yesterday
    } else {
      return 0
    }

    let count = 0
    while (activeDates.has(current)) {
      count++
      const d = new Date(current + 'T00:00:00')
      d.setDate(d.getDate() - 1)
      current = d.toISOString().slice(0, 10)
    }
    return count
  }, [days])

  return (
    <div style={{ display: 'flex', flexWrap: 'wrap', gap: 24, marginBottom: 16 }}>
      <StatCard label="Sessions" value={String(totals.sessions)} accent />
      <StatCard label="Executions" value={String(totals.executions)} />
      <StatCard label="Commits" value={String(totals.commits)} />
      <StatCard label="Active days" value={String(totals.active_days)} sublabel={streak > 0 ? `${streak} day streak` : undefined} />
      <StatCard label="Total cost" value={`$${totals.cost_usd.toFixed(2)}`} color="var(--color-success)" />
      <StatCard label="Total tokens" value={formatCompact(totalTokens)} sublabel={`${formatCompact(totals.input_tokens)} in / ${formatCompact(totals.output_tokens)} out`} />
    </div>
  )
}

function StatCard({ label, value, sublabel, accent, color }: {
  label: string
  value: string
  sublabel?: string
  accent?: boolean
  color?: string
}) {
  return (
    <div style={{ minWidth: 100 }}>
      <div
        className="font-mono"
        style={{
          fontSize: 22,
          fontWeight: 600,
          color: color ?? (accent ? 'var(--color-accent-primary)' : 'var(--color-text-primary)'),
          lineHeight: 1.2,
        }}
      >
        {value}
      </div>
      <div style={{ fontSize: 11, color: 'var(--color-text-muted)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
        {label}
      </div>
      {sublabel && (
        <div style={{ fontSize: 10, color: 'var(--color-text-muted)', marginTop: 2 }}>
          {sublabel}
        </div>
      )}
    </div>
  )
}

/* ---------- Main Heatmap ---------- */

interface ContributionHeatmapProps {
  days: HeatmapDayBucket[]
  startDate: string
  endDate: string
}

export function ContributionHeatmap({ days, startDate, endDate }: ContributionHeatmapProps) {
  const yearRanges = useMemo(() => buildYearRanges(days), [days])
  const [selectedRange, setSelectedRange] = useState(0) // 0 = current year

  const range = yearRanges[selectedRange] ?? { from: startDate, to: endDate, label: 'All' }

  // Always split into per-year slices, newest first.
  // Each slice spans the FULL year (Jan 5 – Dec 31) regardless of the
  // selected date range.  This keeps every calendar row the same width
  // and cell size.  Jan 5 avoids a Nivo ISO-week rendering quirk.
  const yearSlices = useMemo(() => {
    const fromYear = new Date(range.from).getFullYear()
    const toYear = new Date(range.to).getFullYear()
    const slices: { from: string; to: string; label: string }[] = []
    for (let y = toYear; y >= fromYear; y--) {
      slices.push({ from: `${y}-01-05`, to: `${y}-12-31`, label: String(y) })
    }
    return slices
  }, [range.from, range.to])

  // Sessions-based data for heatmap intensity
  const data = useMemo(
    () =>
      days
        .filter((d) => d.breakdown.sessions > 0)
        .map((d) => ({
          day: d.date,
          value: d.breakdown.sessions,
        })),
    [days],
  )

  const maxValue = Math.max(1, ...data.map((d) => d.value))

  // Build a lookup for quick tooltip access
  const dayLookup = useMemo(() => {
    const map = new Map<string, HeatmapDayBucket>()
    for (const d of days) map.set(d.date, d)
    return map
  }, [days])

  const calendarProps = {
    emptyColor: '#1a1a2e',
    colors: ['#1a3366', '#2952a3', '#3d6dd9', '#4D80FF'] as const,
    minValue: 0,
    maxValue,
    monthSpacing: 4,
    monthBorderColor: 'transparent',
    dayBorderWidth: 2,
    dayBorderColor: '#0F0F1A',
    daySpacing: 1,
    theme: {
      text: { fill: '#8899BB', fontSize: 11 },
      labels: { text: { fill: '#8899BB', fontSize: 11 } },
    },
  } as const

  return (
    <div>
      <SummaryStats days={days} />

      <div style={{ display: 'flex', gap: 0 }}>
        {/* Year selector */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: 4, paddingTop: 20, paddingRight: 12, flexShrink: 0 }}>
          {yearRanges.map((r, i) => (
            <button
              key={r.label}
              onClick={() => setSelectedRange(i)}
              style={{
                padding: '4px 10px',
                borderRadius: 6,
                fontSize: 12,
                fontWeight: selectedRange === i ? 600 : 400,
                color: selectedRange === i ? 'var(--color-text-primary)' : 'var(--color-text-muted)',
                background: selectedRange === i ? 'var(--color-surface-elevated)' : 'transparent',
                border: 'none',
                cursor: 'pointer',
                textAlign: 'left',
                whiteSpace: 'nowrap',
                transition: 'all 0.15s',
              }}
            >
              {r.label}
            </button>
          ))}
        </div>

        {/* Heatmap — one calendar per year, newest first */}
        <div style={{ flex: 1, minWidth: 700 }}>
          {yearSlices.map((slice) => (
            <div
              key={slice.label}
              className="heatmap-container"
              style={{ height: 160, position: 'relative' }}
            >
              <ResponsiveCalendar
                data={data}
                from={slice.from}
                to={slice.to}
                {...calendarProps}
                margin={{ top: 25, right: 20, bottom: 0, left: 30 }}
                tooltip={({ day }) => {
                  const bucket = dayLookup.get(day)
                  return <HeatmapTooltip data={{ day, bucket }} />
                }}
              />
            </div>
          ))}
        </div>
      </div>

      {/* Legend */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'flex-end', gap: 6, marginTop: 8, fontSize: 11, color: 'var(--color-text-muted)' }}>
        <span>Less</span>
        {['#1a1a2e', '#1a3366', '#2952a3', '#3d6dd9', '#4D80FF'].map((c) => (
          <div
            key={c}
            style={{
              width: 12,
              height: 12,
              borderRadius: 2,
              background: c,
              border: '1px solid rgba(255,255,255,0.05)',
            }}
          />
        ))}
        <span>More</span>
      </div>
    </div>
  )
}
