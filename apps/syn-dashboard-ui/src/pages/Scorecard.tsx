import { clsx } from 'clsx'
import { Gauge } from 'lucide-react'
import { useEffect, useState } from 'react'

import { getScorecard } from '../api/scorecard'
import type { Scorecard as ScorecardData, ScorecardDailyPoint, ScorecardTarget } from '../api/scorecard'
import { Card, CardContent, CardHeader, EmptyState } from '../components'

const PILL: Record<ScorecardTarget['status'], { label: string; className: string }> = {
  on_track: { label: 'On track', className: 'bg-[var(--color-success)]/15 text-[var(--color-success)]' },
  off_track: { label: 'Off track', className: 'bg-[var(--color-error)]/15 text-[var(--color-error)]' },
  no_data: { label: 'No data', className: 'bg-[var(--color-border)] text-[var(--color-text-muted)]' },
}

/** One daily value per point; a day with no value breaks the line rather than reading as zero. */
function Sparkline({ label, values }: { label: string; values: (number | null)[] }) {
  const known = values.filter((v): v is number => v !== null)
  const max = Math.max(...known, 1)
  const step = values.length > 1 ? 100 / (values.length - 1) : 0
  const segments: string[][] = [[]]
  values.forEach((v, i) => {
    if (v === null) segments.push([])
    else segments[segments.length - 1].push(`${(i * step).toFixed(1)},${(28 - (v / max) * 26).toFixed(1)}`)
  })
  return (
    <svg viewBox="0 0 100 30" preserveAspectRatio="none" className="h-8 w-full" role="img" aria-label={label}>
      {segments
        .filter((points) => points.length > 0)
        .map((points, i) =>
          points.length === 1 ? (
            <circle key={i} cx={points[0].split(',')[0]} cy={points[0].split(',')[1]} r="1.5" fill="var(--color-accent)" />
          ) : (
            <polyline
              key={i}
              points={points.join(' ')}
              fill="none"
              stroke="var(--color-accent)"
              strokeWidth="1.5"
              vectorEffect="non-scaling-stroke"
            />
          ),
        )}
    </svg>
  )
}

function trendOf(name: string, daily: ScorecardDailyPoint[]): (number | null)[] {
  switch (name) {
    case 'Platform-failure-free completion':
      return daily.map((d) => d.counts.platform_failure_free_rate ?? null)
    case 'Median verify tokens':
      return daily.map((d) => d.median_verify_tokens ?? null)
    case 'Stable concurrency':
      return daily.map((d) => d.peak_concurrency)
    default:
      return daily.map(() => null)
  }
}

function TargetTile({ target, daily }: { target: ScorecardTarget; daily: ScorecardDailyPoint[] }) {
  const pill = PILL[target.status]
  return (
    <Card className="min-w-0 p-4">
      <div className="flex items-start justify-between gap-2">
        <p className="min-w-0 text-xs text-[var(--color-text-secondary)]">{target.name}</p>
        <span className={clsx('shrink-0 rounded-full px-2 py-0.5 text-[10px] font-medium', pill.className)}>
          {pill.label}
        </span>
      </div>
      <p className="mt-2 text-2xl font-semibold text-[var(--color-text-primary)]">{target.actual_display}</p>
      <p className="text-xs text-[var(--color-text-muted)]">target {target.target_display}</p>
      <div className="mt-2">
        <Sparkline label={`${target.name}, daily`} values={trendOf(target.name, daily)} />
      </div>
    </Card>
  )
}

const FAILURE_ROWS: { label: string; key: keyof ScorecardData['counts'] }[] = [
  { label: 'Completed', key: 'completed' },
  { label: 'Failed: platform', key: 'failed_platform' },
  { label: 'Failed: task', key: 'failed_task' },
  { label: 'Failed: correct refusal', key: 'failed_correct_refusal' },
  { label: 'Failed: unclassified', key: 'failed_unclassified' },
  { label: 'Cancelled', key: 'cancelled' },
]

export function Scorecard() {
  const [window, setWindow] = useState('7d')
  const [data, setData] = useState<ScorecardData | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let live = true
    getScorecard(window)
      .then((d) => {
        if (!live) return
        setData(d)
        setError(null)
      })
      .catch((e: unknown) => live && setError(e instanceof Error ? e.message : String(e)))
    return () => {
      live = false
    }
  }, [window])

  return (
    <div className="min-w-0">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h1 className="text-lg font-semibold text-[var(--color-text-primary)]">Scorecard</h1>
        <div className="flex gap-1" role="group" aria-label="Window">
          {['1d', '7d', '30d'].map((w) => (
            <button
              key={w}
              type="button"
              onClick={() => setWindow(w)}
              aria-pressed={w === window}
              className={clsx(
                'rounded px-2 py-1 text-xs',
                w === window
                  ? 'bg-[var(--color-accent)] text-white'
                  : 'text-[var(--color-text-secondary)] hover:bg-[var(--color-surface-elevated)]',
              )}
            >
              {w}
            </button>
          ))}
        </div>
      </div>
      {error && (
        <div className="mt-6">
          <EmptyState icon={Gauge} title="Scorecard unavailable" description={error} />
        </div>
      )}
      {data && !error && (
        <>
          <p className="mt-1 text-xs text-[var(--color-text-secondary)]">{data.scope}</p>
          <div className="mt-4 grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-4">
            {data.targets.map((t) => (
              <TargetTile key={t.name} target={t} daily={data.daily} />
            ))}
          </div>
          <p className="mt-2 text-xs text-[var(--color-text-muted)]">{data.delivery.scope}</p>

          <div className="mt-6 grid grid-cols-1 gap-4 lg:grid-cols-2">
            <Card className="min-w-0">
              <CardHeader title="Outcomes" subtitle={`${data.counts.total} finished chains · ${data.total_cost_display}`} />
              <CardContent>
                <table className="w-full text-sm">
                  <tbody>
                    {FAILURE_ROWS.map((row) => (
                      <tr key={row.key} className="border-b border-[var(--color-border)] last:border-0">
                        <td className="py-1.5 text-[var(--color-text-secondary)]">{row.label}</td>
                        <td className="py-1.5 text-right tabular-nums text-[var(--color-text-primary)]">
                          {String(data.counts[row.key])}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                <p className="mt-2 text-xs text-[var(--color-text-muted)]">{data.cost_scope}</p>
              </CardContent>
            </Card>

            <Card className="min-w-0">
              <CardHeader
                title="Throughput"
                subtitle={`avg ${data.throughput.average_concurrency_display} · peak ${data.throughput.peak_concurrency} concurrent`}
              />
              <CardContent>
                <p className="text-sm text-[var(--color-text-primary)]">
                  Queue wait: median {data.throughput.median_queue_wait_display}, p90{' '}
                  {data.throughput.p90_queue_wait_display} ({data.throughput.queue_waits_measured} runs)
                </p>
                <p className="mt-2 text-xs text-[var(--color-text-muted)]">{data.throughput.scope}</p>
              </CardContent>
            </Card>
          </div>

          <Card className="mt-4 min-w-0">
            <CardHeader title="Tokens and cost per phase type" />
            <CardContent>
              <div className="overflow-x-auto">
                <table className="w-full min-w-[32rem] text-sm">
                  <thead>
                    <tr className="text-left text-xs text-[var(--color-text-muted)]">
                      <th className="py-1 font-medium">Phase</th>
                      <th className="py-1 text-right font-medium">Runs</th>
                      <th className="py-1 text-right font-medium">Median</th>
                      <th className="py-1 text-right font-medium">p90</th>
                      <th className="py-1 text-right font-medium">Cache read</th>
                      <th className="py-1 text-right font-medium">Tool calls</th>
                      <th className="py-1 text-right font-medium">Tokens/call</th>
                      <th className="py-1 text-right font-medium">Median cost</th>
                      <th className="py-1 text-right font-medium">p90 cost</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.phases.map((p) => (
                      <tr key={p.phase_type} className="border-t border-[var(--color-border)] tabular-nums">
                        <td className="py-1.5 text-[var(--color-text-primary)]">{p.phase_type}</td>
                        <td className="py-1.5 text-right">{p.phase_count}</td>
                        <td className="py-1.5 text-right">{p.median_tokens_display}</td>
                        <td className="py-1.5 text-right">{p.p90_tokens_display}</td>
                        <td className="py-1.5 text-right">{p.cache_read_share_display}</td>
                        <td className="py-1.5 text-right">{p.median_tool_calls_display}</td>
                        <td className="py-1.5 text-right">{p.tokens_per_tool_call_display}</td>
                        <td className="py-1.5 text-right">{p.median_cost_display}</td>
                        <td className="py-1.5 text-right">{p.p90_cost_display}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <p className="mt-2 text-xs text-[var(--color-text-muted)]">{data.phases_scope}</p>
            </CardContent>
          </Card>
          <p className="mt-4 text-xs text-[var(--color-text-muted)]">{data.eval_quality_scope}</p>
        </>
      )}
    </div>
  )
}
