import {
  Bar,
  BarChart,
  Cell,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'

import { Card, CardContent, CardHeader } from '../../components'

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
              <XAxis type="number" tick={{ fill: 'var(--color-text-muted)', fontSize: 11 }} />
              <YAxis
                type="category"
                dataKey="name"
                tick={{ fill: 'var(--color-text-secondary)', fontSize: 11 }}
                width={100}
              />
              <Tooltip
                contentStyle={{
                  backgroundColor: 'var(--color-surface-elevated)',
                  border: '1px solid var(--color-border)',
                  borderRadius: '8px',
                  fontSize: '12px',
                }}
                formatter={(value: number | string) => [Number(value).toLocaleString(), 'tokens']}
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
