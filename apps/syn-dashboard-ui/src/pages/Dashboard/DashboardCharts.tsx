import {
  Cell,
  Pie,
  PieChart,
  ResponsiveContainer,
} from 'recharts'

import type { ValueType } from 'recharts/types/component/DefaultTooltipContent'
import type { MetricsResponse } from '../../types'
import { ChartTooltip } from '../../components'

interface ChartDataItem {
  [key: string]: unknown
  name: string
  value: number
  fill: string
}

function ChartLegend({ items }: { items: ChartDataItem[] }) {
  return (
    <div className="flex justify-center gap-6 -mt-4">
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
  const tokenDistribution: ChartDataItem[] = metrics
    ? [
      { name: 'Input', value: metrics.total_input_tokens, fill: '#4D80FF' },
      { name: 'Output', value: metrics.total_output_tokens, fill: '#5A8CFF' },
    ]
    : []

  return (
    <DonutChart
      data={tokenDistribution}
      emptyMessage="No token data yet"
      tooltipFormatter={(value) => [Number(Array.isArray(value) ? value[0] : value ?? 0).toLocaleString(), 'tokens']}
    />
  )
}

export function WorkflowStatusChart({ metrics }: DashboardChartsProps) {
  const workflowStatusData: ChartDataItem[] = metrics
    ? [
      { name: 'Completed', value: metrics.completed_workflows, fill: '#22c55e' },
      { name: 'Failed', value: metrics.failed_workflows, fill: '#ef4444' },
      { name: 'Other', value: metrics.total_workflows - metrics.completed_workflows - metrics.failed_workflows, fill: '#4D80FF' },
    ].filter(d => d.value > 0)
    : []

  return (
    <DonutChart
      data={workflowStatusData}
      emptyMessage="No workflow data yet"
    />
  )
}
