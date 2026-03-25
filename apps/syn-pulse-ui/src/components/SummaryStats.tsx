import { useMemo } from 'react'
import type { HeatmapDayBucket } from '../types'
import { formatCompact } from './HeatmapTooltip'

interface SummaryStatsProps {
  days: HeatmapDayBucket[]
}

function toDateString(date: Date): string {
  return date.toISOString().slice(0, 10)
}

function previousDay(dateStr: string): string {
  const d = new Date(dateStr + 'T00:00:00')
  d.setDate(d.getDate() - 1)
  return toDateString(d)
}

function collectActiveDates(days: HeatmapDayBucket[]): Set<string> {
  const activeDates = new Set<string>()
  for (const d of days) {
    if (d.breakdown.sessions > 0) activeDates.add(d.date)
  }
  return activeDates
}

function findStreakStart(activeDates: Set<string>): string | null {
  const now = new Date()
  const today = toDateString(now)
  if (activeDates.has(today)) return today
  const yesterday = previousDay(today)
  if (activeDates.has(yesterday)) return yesterday
  return null
}

function calculateStreak(days: HeatmapDayBucket[]): number {
  const activeDates = collectActiveDates(days)
  let current = findStreakStart(activeDates)
  if (!current) return 0

  let count = 0
  while (activeDates.has(current)) {
    count++
    current = previousDay(current)
  }
  return count
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
  const streak = useMemo(() => calculateStreak(days), [days])

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
