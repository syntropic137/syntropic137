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

interface TokenBreakdownChartProps {
  inputTokens: number
  outputTokens: number
}

export function TokenBreakdownChart({ inputTokens, outputTokens }: TokenBreakdownChartProps) {
  const tokenChartData = [
    { name: 'Input', tokens: inputTokens, fill: '#6366f1' },
    { name: 'Output', tokens: outputTokens, fill: '#22c55e' },
  ]

  return (
    <Card>
      <CardHeader title="Token Breakdown" subtitle="Input vs output token distribution" />
      <CardContent className="h-[200px]">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={tokenChartData} margin={{ top: 10, right: 20, left: 0, bottom: 0 }}>
            <XAxis dataKey="name" tick={{ fill: 'var(--color-text-secondary)', fontSize: 12 }} />
            <YAxis tick={{ fill: 'var(--color-text-muted)', fontSize: 11 }} />
            <Tooltip
              contentStyle={{
                backgroundColor: 'var(--color-surface-elevated)',
                border: '1px solid var(--color-border)',
                borderRadius: '8px',
                fontSize: '12px',
              }}
              formatter={(value: number) => [value.toLocaleString(), 'tokens']}
            />
            <Bar dataKey="tokens" radius={[4, 4, 0, 0]}>
              {tokenChartData.map((entry, index) => (
                <Cell key={`cell-${index}`} fill={entry.fill} />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </CardContent>
    </Card>
  )
}
