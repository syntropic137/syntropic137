import {
  Cell,
  Pie,
  PieChart,
  ResponsiveContainer,
} from 'recharts'

import type { ValueType } from 'recharts/types/component/DefaultTooltipContent'
import type { MetricsResponse } from '../../types'
import { ChartTooltip } from '../../components'
import { type ChartDataItem, statusSlices, tokenSegments } from './chartData'

function ChartLegend({ items }: { items: ChartDataItem[] }) {
  return (
    <div className="flex flex-wrap justify-center gap-x-4 gap-y-1 -mt-4">
      {items.map((item) => (
        <div key={item.name} className="flex items-center gap-2">
          <div
            className="h-3 w-3 rounded-full"
            style={{ backgroundColor: item.fill }}
          />
          <span className="text-xs text-[var(--color-text-secondary)]">{item.name}</span>
        </div>
      ))}
    </div>
  )
}

function DonutChart({
  data,
  emptyMessage,
  tooltipFormatter,
}: {
  data: ChartDataItem[]
  emptyMessage: string
  tooltipFormatter?: (value: ValueType | undefined) => [string, string]
}) {
  if (!data.some((d) => d.value > 0)) {
    return (
      <div className="flex h-full items-center justify-center text-sm text-[var(--color-text-muted)]">
        {emptyMessage}
      </div>
    )
  }

  return (
    <>
      <ResponsiveContainer width="100%" height="100%">
        <PieChart>
          <Pie
            data={data}
            cx="50%"
            cy="50%"
            innerRadius={50}
            outerRadius={70}
            paddingAngle={2}
            dataKey="value"
            stroke="none"
          >
            {data.map((entry, index) => (
              <Cell key={`cell-${index}`} fill={entry.fill} />
            ))}
          </Pie>
          <ChartTooltip formatter={tooltipFormatter} />
        </PieChart>
      </ResponsiveContainer>
      <ChartLegend items={data} />
    </>
  )
}

interface DashboardChartsProps {
  metrics: MetricsResponse | null
}

export function DashboardCharts({ metrics }: DashboardChartsProps) {
  return (
    <DonutChart
      data={metrics ? tokenSegments(metrics) : []}
      emptyMessage="No token data yet"
      tooltipFormatter={(value) => [Number(Array.isArray(value) ? value[0] : value ?? 0).toLocaleString(), 'tokens']}
    />
  )
}

export function WorkflowStatusChart({ metrics }: DashboardChartsProps) {
  return (
    <DonutChart
      data={metrics ? statusSlices(metrics.execution_status_counts) : []}
      emptyMessage="No workflow data yet"
    />
  )
}
