import { useMemo, useState } from 'react'
import { ResponsiveCalendar } from '@nivo/calendar'
import type { HeatmapDayBucket } from '../types'
import { HeatmapLegend } from './HeatmapLegend'
import { HeatmapTooltip } from './HeatmapTooltip'
import { SummaryStats } from './SummaryStats'
import { YearSelector } from './YearSelector'

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

  // Individual year ranges, newest first (like GitHub).
  // Jan 5 start avoids a Nivo ISO-week rendering quirk.
  for (let y = maxYear; y >= minYear; y--) {
    ranges.push({ from: `${y}-01-05`, to: `${y}-12-31`, label: String(y) })
  }

  return ranges
}

interface ContributionHeatmapProps {
  days: HeatmapDayBucket[]
  startDate: string
  endDate: string
}

export function ContributionHeatmap({ days, startDate, endDate }: ContributionHeatmapProps) {
  const yearRanges = useMemo(() => buildYearRanges(days), [days])
  const [selectedRange, setSelectedRange] = useState(0)

  const range = yearRanges[selectedRange] ?? { from: startDate, to: endDate, label: 'All' }

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
    () =>
      days
        .filter((d) => d.breakdown.sessions > 0)
        .map((d) => ({ day: d.date, value: d.breakdown.sessions })),
    [days],
  )

  const maxValue = Math.max(1, ...data.map((d) => d.value))

  const dayLookup = useMemo(() => {
    const map = new Map<string, HeatmapDayBucket>()
    for (const d of days) map.set(d.date, d)
    return map
  }, [days])

  const calendarProps = {
    emptyColor: '#1a1a2e',
    colors: ['#1a3366', '#2952a3', '#3d6dd9', '#4D80FF'] as string[],
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
        <YearSelector labels={yearRanges.map((r) => r.label)} selectedIndex={selectedRange} onSelect={setSelectedRange} />
        <div style={{ flex: 1, minWidth: 700 }}>
          {yearSlices.map((slice) => (
            <div key={slice.label} className="heatmap-container" style={{ height: 160, position: 'relative' }}>
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
      <HeatmapLegend />
    </div>
  )
}
