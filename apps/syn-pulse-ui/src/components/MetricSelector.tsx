import clsx from 'clsx'
import type { MetricKey } from '../types'

const METRICS: { key: MetricKey; label: string }[] = [
  { key: 'sessions', label: 'Sessions' },
  { key: 'executions', label: 'Executions' },
  { key: 'commits', label: 'Commits' },
  { key: 'cost_usd', label: 'Cost (USD)' },
  { key: 'tokens', label: 'Tokens' },
]

interface MetricSelectorProps {
  value: MetricKey
  onChange: (metric: MetricKey) => void
}

export function MetricSelector({ value, onChange }: MetricSelectorProps) {
  return (
    <div className="flex flex-wrap gap-2">
      {METRICS.map((m) => (
        <button
          key={m.key}
          onClick={() => onChange(m.key)}
          className={clsx(
            'px-3 py-1.5 rounded-lg text-sm font-medium transition-colors',
            value === m.key
              ? 'text-white'
              : 'text-[var(--color-text-secondary)] hover:text-[var(--color-text-primary)]',
          )}
          style={value === m.key ? {
            background: 'var(--color-accent-primary)',
          } : {
            background: 'var(--color-surface-elevated)',
          }}
        >
          {m.label}
        </button>
      ))}
    </div>
  )
}
