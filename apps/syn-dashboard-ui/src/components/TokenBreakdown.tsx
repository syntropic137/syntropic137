import { Zap } from 'lucide-react'
import { Card, CardContent, CardHeader } from './Card'
import { formatTokens } from '../utils/formatters'

interface TokenBreakdownProps {
  inputTokens: number
  outputTokens: number
  cacheCreationTokens: number
  cacheReadTokens: number
}

interface TokenRow {
  label: string
  tokens: number
  color: string
  rateLabel?: string
}

export function TokenBreakdown({
  inputTokens,
  outputTokens,
  cacheCreationTokens,
  cacheReadTokens,
}: TokenBreakdownProps) {
  const totalAllTokens = inputTokens + outputTokens + cacheCreationTokens + cacheReadTokens

  if (totalAllTokens === 0) return null

  const rows: TokenRow[] = [
    { label: 'Cache Read', tokens: cacheReadTokens, color: 'bg-emerald-500', rateLabel: '0.1x rate' },
    { label: 'Cache Write', tokens: cacheCreationTokens, color: 'bg-amber-500', rateLabel: '1.25x rate' },
    { label: 'Output', tokens: outputTokens, color: 'bg-violet-500' },
    { label: 'Input', tokens: inputTokens, color: 'bg-indigo-500' },
  ]
    .filter(r => r.tokens > 0)
    .sort((a, b) => b.tokens - a.tokens)

  const hasCacheTokens = cacheCreationTokens > 0 || cacheReadTokens > 0

  return (
    <Card>
      <CardHeader
        title="Token Usage"
        subtitle={hasCacheTokens ? 'Breakdown by token type' : 'Input and output tokens'}
        action={
          <div className="flex items-center gap-2">
            <Zap className="h-4 w-4 text-[var(--color-accent)]" />
            <span className="text-lg font-bold text-[var(--color-text-primary)]">
              {formatTokens(totalAllTokens)}
            </span>
            <span className="text-xs text-[var(--color-text-muted)]">total</span>
          </div>
        }
      />
      <CardContent>
        <div className="space-y-3">
          {rows.map(row => {
            const percentage = totalAllTokens > 0
              ? (row.tokens / totalAllTokens) * 100
              : 0

            return (
              <div key={row.label} className="space-y-1">
                <div className="flex items-center justify-between text-sm">
                  <div className="flex items-center gap-2">
                    <div className={`h-2.5 w-2.5 rounded-sm ${row.color}`} />
                    <span className="text-[var(--color-text-secondary)]">{row.label}</span>
                    {row.rateLabel && (
                      <span className="text-xs px-1.5 py-0.5 rounded bg-[var(--color-surface-elevated)] text-[var(--color-text-muted)]">
                        {row.rateLabel}
                      </span>
                    )}
                  </div>
                  <div className="flex items-center gap-3">
                    <span className="text-[var(--color-text-primary)] font-medium tabular-nums">
                      {row.tokens.toLocaleString()}
                    </span>
                    <span className="text-xs text-[var(--color-text-muted)] w-12 text-right tabular-nums">
                      {percentage.toFixed(1)}%
                    </span>
                  </div>
                </div>
                <div className="h-1.5 bg-[var(--color-surface-elevated)] rounded-full overflow-hidden">
                  <div
                    className={`h-full ${row.color} rounded-full transition-all`}
                    style={{ width: `${Math.max(percentage, 0.5)}%` }}
                  />
                </div>
              </div>
            )
          })}
        </div>
      </CardContent>
    </Card>
  )
}
