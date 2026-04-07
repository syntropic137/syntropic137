import { useEffect, useMemo, useState } from 'react'
// TODO(#624): Dashboard uses recharts elsewhere — consolidate on one charting
// library during the redesign (migrate recharts→nivo or rebuild heatmap in recharts).
import { ResponsiveCalendar } from '@nivo/calendar'

import { API_BASE, fetchJSON } from '../../api/base'
import { Card, CardContent, CardHeader } from '../../components'

// --- Types ---

interface HeatmapDayBucket {
  date: string
  count: number
  breakdown: {
    sessions: number
    executions: number
    commits: number
    cost_usd: number
    tokens: number
    input_tokens: number
    output_tokens: number
    cache_creation_tokens: number
    cache_read_tokens: number
  }
}

interface ContributionHeatmapResult {
  metric: string
  start_date: string
  end_date: string
  total: number
  days: HeatmapDayBucket[]
}

// --- API ---

async function getContributionHeatmap(params: {
  organization_id?: string
  system_id?: string
  repo_id?: string
}): Promise<ContributionHeatmapResult> {
  const query = new URLSearchParams()
  for (const [k, v] of Object.entries(params)) {
    if (v) query.set(k, v)
  }
  query.set('metric', 'sessions')
  const qs = query.toString()
  return fetchJSON(`${API_BASE}/insights/contribution-heatmap${qs ? `?${qs}` : ''}`)
}

// --- Helpers ---

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
  const dates = days.map((d) => new Date(d.date + 'T00:00:00'))
  const minYear = Math.min(...dates.map((d) => d.getFullYear()))
  const maxYear = Math.max(...dates.map((d) => d.getFullYear()))
  const ranges: YearRange[] = []
  for (let y = maxYear; y >= minYear; y--) {
    ranges.push({ from: `${y}-01-05`, to: `${y}-12-31`, label: String(y) })
  }
  return ranges
}

// --- Sub-components ---

function HeatmapTooltip({ day, bucket }: { day: string; bucket: HeatmapDayBucket | undefined }) {
  const date = new Date(day + 'T00:00:00')
  const formatted = date.toLocaleDateString('en-US', {
    weekday: 'short', month: 'short', day: 'numeric', year: 'numeric',
  })

  if (!bucket || bucket.count === 0) {
    return (
      <div className="rounded-lg border border-[var(--color-border)] bg-[var(--color-surface)] px-3 py-2 text-xs shadow-lg">
        <div className="font-medium text-[var(--color-text-primary)]">{formatted}</div>
        <div className="text-[var(--color-text-muted)]">No activity</div>
      </div>
    )
  }

  const b = bucket.breakdown
  return (
    <div className="rounded-lg border border-[var(--color-border)] bg-[var(--color-surface)] px-4 py-3 text-xs shadow-lg" style={{ minWidth: 220 }}>
      <div className="mb-2 text-[13px] font-medium text-[var(--color-text-primary)]">{formatted}</div>
      <div className="mb-2 flex gap-4">
        <TooltipStat label="Sessions" value={String(b.sessions)} highlight />
        <TooltipStat label="Executions" value={String(b.executions)} />
        <TooltipStat label="Commits" value={String(b.commits)} />
      </div>
      <div className="my-1.5 border-t border-[var(--color-border)]" />
      <div className="space-y-0.5 text-[var(--color-text-secondary)]">
        <div className="mb-1 text-[10px] uppercase tracking-wider text-[var(--color-text-muted)]">Tokens</div>
        <TooltipRow label="Input" value={formatCompact(b.input_tokens)} />
        <TooltipRow label="Output" value={formatCompact(b.output_tokens)} />
        <TooltipRow label="Cache create" value={formatCompact(b.cache_creation_tokens)} />
        <TooltipRow label="Cache read" value={formatCompact(b.cache_read_tokens)} />
      </div>
      <div className="my-1.5 border-t border-[var(--color-border)]" />
      <div className="flex justify-between">
        <span className="text-[var(--color-text-muted)]">Cost</span>
        <span className="font-mono font-semibold text-emerald-400">${b.cost_usd.toFixed(2)}</span>
      </div>
    </div>
  )
}

function TooltipStat({ label, value, highlight }: { label: string; value: string; highlight?: boolean }) {
  return (
    <div className="text-center">
      <div className={`font-mono text-base font-semibold ${highlight ? 'text-[var(--color-accent)]' : 'text-[var(--color-text-primary)]'}`}>
        {value}
      </div>
      <div className="text-[10px] uppercase tracking-wider text-[var(--color-text-muted)]">{label}</div>
    </div>
  )
}

function TooltipRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex justify-between gap-4">
      <span className="text-[var(--color-text-muted)]">{label}</span>
      <span className="font-mono text-[var(--color-text-primary)]">{value}</span>
    </div>
  )
}

function SummaryStats({ days }: { days: HeatmapDayBucket[] }) {
  const totals = useMemo(() => {
    const t = { sessions: 0, executions: 0, commits: 0, cost_usd: 0, input_tokens: 0, output_tokens: 0, cache_creation_tokens: 0, cache_read_tokens: 0, active_days: 0 }
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

  return (
    <div className="flex flex-wrap gap-6 mb-3">
      <StatCard label="Sessions" value={String(totals.sessions)} accent />
      <StatCard label="Executions" value={String(totals.executions)} />
      <StatCard label="Commits" value={String(totals.commits)} />
      <StatCard label="Active days" value={String(totals.active_days)} />
      <StatCard label="Total cost" value={`$${totals.cost_usd.toFixed(2)}`} color="text-emerald-400" />
      <StatCard label="Total tokens" value={formatCompact(totalTokens)} sublabel={`${formatCompact(totals.input_tokens)} in / ${formatCompact(totals.output_tokens)} out`} />
    </div>
  )
}

function StatCard({ label, value, sublabel, accent, color }: {
  label: string; value: string; sublabel?: string; accent?: boolean; color?: string
}) {
  return (
    <div className="min-w-[90px]">
      <div className={`font-mono text-xl font-semibold leading-tight ${color ?? (accent ? 'text-[var(--color-accent)]' : 'text-[var(--color-text-primary)]')}`}>
        {value}
      </div>
      <div className="text-[11px] uppercase tracking-wider text-[var(--color-text-muted)]">{label}</div>
      {sublabel && <div className="mt-0.5 text-[10px] text-[var(--color-text-muted)]">{sublabel}</div>}
    </div>
  )
}

function YearSelector({ labels, selectedIndex, onSelect }: {
  labels: string[]; selectedIndex: number; onSelect: (i: number) => void
}) {
  return (
    <div className="flex shrink-0 flex-col gap-1 pr-3 pt-5">
      {labels.map((label, i) => (
        <button
          key={label}
          onClick={() => onSelect(i)}
          className={`rounded-md px-2.5 py-1 text-left text-xs transition-colors ${
            selectedIndex === i
              ? 'bg-[var(--color-surface-elevated)] font-semibold text-[var(--color-text-primary)]'
              : 'text-[var(--color-text-muted)] hover:text-[var(--color-text-secondary)]'
          }`}
        >
          {label}
        </button>
      ))}
    </div>
  )
}

function HeatmapLegend() {
  const colors = ['#1a1a2e', '#1a3366', '#2952a3', '#3d6dd9', '#4D80FF']
  return (
    <div className="mt-2 flex items-center justify-end gap-1.5 text-[11px] text-[var(--color-text-muted)]">
      <span>Less</span>
      {colors.map((c) => (
        <div key={c} className="h-3 w-3 rounded-sm border border-white/5" style={{ background: c }} />
      ))}
      <span>More</span>
    </div>
  )
}

// --- Main Heatmap ---

function HeatmapChart({ days, startDate, endDate }: { days: HeatmapDayBucket[]; startDate: string; endDate: string }) {
  const yearRanges = useMemo(() => buildYearRanges(days), [days])
  const [selectedRange, setSelectedRange] = useState(0)
  const range = yearRanges[selectedRange] ?? { from: startDate, to: endDate }

  const yearSlices = useMemo(() => {
    const fromYear = new Date(range.from).getFullYear()
    const toYear = new Date(range.to).getFullYear()
    const slices: YearRange[] = []
    for (let y = toYear; y >= fromYear; y--) {
      slices.push({ from: `${y}-01-05`, to: `${y}-12-31`, label: String(y) })
    }
    return slices
  }, [range.from, range.to])

  const data = useMemo(
    () => days.filter((d) => d.breakdown.sessions > 0).map((d) => ({ day: d.date, value: d.breakdown.sessions })),
    [days],
  )

  const maxValue = Math.max(1, ...data.map((d) => d.value))

  const dayLookup = useMemo(() => {
    const map = new Map<string, HeatmapDayBucket>()
    for (const d of days) map.set(d.date, d)
    return map
  }, [days])

  return (
    <div>
      <SummaryStats days={days} />
      <div className="flex">
        <YearSelector labels={yearRanges.map((r) => r.label)} selectedIndex={selectedRange} onSelect={setSelectedRange} />
        <div className="min-w-[700px] flex-1">
          {yearSlices.map((slice) => (
            <div key={slice.label} style={{ height: 160, position: 'relative' }}>
              <ResponsiveCalendar
                data={data}
                from={slice.from}
                to={slice.to}
                emptyColor="#1a1a2e"
                colors={['#1a3366', '#2952a3', '#3d6dd9', '#4D80FF']}
                minValue={0}
                maxValue={maxValue}
                monthSpacing={4}
                monthBorderColor="transparent"
                dayBorderWidth={2}
                dayBorderColor="#0F0F1A"
                daySpacing={1}
                theme={{
                  text: { fill: '#8899BB', fontSize: 11 },
                  labels: { text: { fill: '#8899BB', fontSize: 11 } },
                }}
                margin={{ top: 25, right: 20, bottom: 0, left: 30 }}
                tooltip={({ day }) => <HeatmapTooltip day={day} bucket={dayLookup.get(day)} />}
              />
            </div>
          ))}
        </div>
      </div>
      <HeatmapLegend />
    </div>
  )
}

// --- Exported Component ---

export function ContributionHeatmap() {
  const [data, setData] = useState<ContributionHeatmapResult | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    setLoading(true)
    getContributionHeatmap({})
      .then((result) => { setData(result); setError(null) })
      .catch((e: Error) => setError(e.message))
      .finally(() => setLoading(false))
  }, [])

  return (
    <Card>
      <CardHeader title="Agent Activity" subtitle="Contribution heatmap across all repositories" />
      <CardContent>
        {loading && (
          <div className="flex items-center justify-center py-12 text-[var(--color-text-muted)]">
            Loading heatmap data...
          </div>
        )}
        {/* TODO(#624): Add a retry button for failed API requests */}
        {error && (
          <div className="flex items-center justify-center py-12 text-red-400">
            {error}
          </div>
        )}
        {data && !loading && !error && (
          <HeatmapChart days={data.days} startDate={data.start_date} endDate={data.end_date} />
        )}
      </CardContent>
    </Card>
  )
}
