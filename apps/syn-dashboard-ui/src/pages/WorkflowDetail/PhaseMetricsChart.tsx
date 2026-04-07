import {
  Bar,
  BarChart,
  Cell,
  ResponsiveContainer,
  XAxis,
  YAxis,
} from 'recharts'

import { Card, CardContent, CardHeader, ChartTooltip } from '../../components'
import { formatTokens } from '../../utils/formatters'

interface PhaseChartDatum {
  name: string
  tokens: number
  cost: number
  fill: string
}

interface PhaseMetricsChartProps {
  phaseChartData: PhaseChartDatum[]
}

export function PhaseMetricsChart({ phaseChartData }: PhaseMetricsChartProps) {
  return (
    <Card>
      <CardHeader title="Token Usage by Phase" subtitle="Tokens consumed per phase" />
      <CardContent className="h-[250px]">
        {phaseChartData.length > 0 ? (
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={phaseChartData} layout="vertical">
              <XAxis
                type="number"
                tick={{ fill: '#94a3b8', fontSize: 11 }}
                tickFormatter={(v: number) => formatTokens(v)}
              />
              <YAxis
                type="category"
                dataKey="name"
                tick={{ fill: '#94a3b8', fontSize: 11 }}
                width={100}
              />
              <ChartTooltip
                position={{ x: 0 }}
                offset={20}
                formatter={(value: number) => [formatTokens(value), 'tokens']}
              />
              <Bar dataKey="tokens" radius={[0, 4, 4, 0]}>
                {phaseChartData.map((entry, index) => (
                  <Cell key={`cell-${index}`} fill={entry.fill} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        ) : (
          <div className="flex h-full items-center justify-center text-sm text-[var(--color-text-muted)]">
            No phase metrics yet
          </div>
        )}
      </CardContent>
    </Card>
  )
}
