import { clsx } from 'clsx'
import { ArrowRight, type LucideIcon } from 'lucide-react'
import { Link } from 'react-router-dom'

interface MetricCardProps {
  title: string
  value: string | number
  subtitle?: string
  icon?: LucideIcon
  trend?: {
    value: number
    isPositive: boolean
  }
  color?: 'default' | 'accent' | 'success' | 'warning' | 'error'
  href?: string
}

const colorClasses = {
  default: {
    icon: 'text-[var(--color-text-secondary)]',
    iconBg: 'bg-[var(--color-surface-elevated)]',
  },
  accent: {
    icon: 'text-blue-400',
    iconBg: 'bg-blue-500/10',
  },
  success: {
    icon: 'text-emerald-400',
    iconBg: 'bg-emerald-500/10',
  },
  warning: {
    icon: 'text-amber-400',
    iconBg: 'bg-amber-500/10',
  },
  error: {
    icon: 'text-red-400',
    iconBg: 'bg-red-500/10',
  },
}

function TrendBadge({ value, isPositive }: { value: number; isPositive: boolean }) {
  return (
    <p className={clsx('mt-2 text-xs font-medium', isPositive ? 'text-emerald-400' : 'text-red-400')}>
      {isPositive ? '↑' : '↓'} {Math.abs(value)}%
    </p>
  )
}

export function MetricCard({
  title,
  value,
  subtitle,
  icon: Icon,
  trend,
  color = 'default',
  href,
}: MetricCardProps) {
  const colors = colorClasses[color]
  const isNumeric = typeof value === 'number'
  const displayValue = isNumeric ? value.toLocaleString() : value
  const valueSize = isNumeric ? 'text-2xl' : 'text-base'

  const content = (
    <div className={clsx(
      'rounded-lg border border-[var(--color-border)] bg-[var(--color-surface)] p-4',
      href && 'cursor-pointer hover:border-[var(--color-accent)] hover:bg-[var(--color-surface-elevated)] transition-colors'
    )}>
      <div className="flex items-start justify-between">
        <div className="flex-1 min-w-0">
          <p className="text-xs font-medium uppercase tracking-wider text-[var(--color-text-secondary)]">
            {title}
          </p>
          <p
            className={clsx('mt-2 font-bold text-[var(--color-text-primary)] truncate', valueSize)}
            title={String(value)}
          >
            {displayValue}
          </p>
          {subtitle && (
            <p className="mt-1 text-xs text-[var(--color-text-muted)]">{subtitle}</p>
          )}
          {trend && <TrendBadge value={trend.value} isPositive={trend.isPositive} />}
        </div>
        {Icon && (
          <div className={clsx('rounded-lg p-2', colors.iconBg)}>
            <Icon className={clsx('h-5 w-5', colors.icon)} />
          </div>
        )}
        {href && (
          <ArrowRight
            className="h-4 w-4 text-[var(--color-text-muted)] ml-2 self-center"
            aria-hidden="true"
          />
        )}
      </div>
    </div>
  )

  if (href) {
    return (
      <Link
        to={href}
        aria-label={`View ${title} details`}
        className="focus:outline-none focus:ring-2 focus:ring-[var(--color-accent)] focus:ring-offset-2 rounded-lg"
      >
        {content}
      </Link>
    )
  }

  return content
}
