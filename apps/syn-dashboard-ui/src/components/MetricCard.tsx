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
  /** Navigate to a route on click. */
  href?: string
  /**
   * Scroll smoothly to the element with this id on click. Use for detail-page
   * cards that jump to a section further down (e.g. tokens → breakdown).
   * Mutually exclusive with `href`.
   */
  scrollToId?: string
}

function scrollToElement(id: string): void {
  const el = document.getElementById(id)
  if (!el) return
  el.scrollIntoView({ behavior: 'smooth', block: 'start' })
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

interface CardBodyProps {
  title: string
  value: string | number
  displayValue: string | number
  valueSize: string
  subtitle?: string
  Icon?: LucideIcon
  iconColors: { icon: string; iconBg: string }
  trend?: { value: number; isPositive: boolean }
  interactive: boolean
}

function CardBody({
  title,
  value,
  displayValue,
  valueSize,
  subtitle,
  Icon,
  iconColors,
  trend,
  interactive,
}: CardBodyProps) {
  return (
    <div
      className={clsx(
        'rounded-lg border border-[var(--color-border)] bg-[var(--color-surface)] p-4',
        interactive &&
          'cursor-pointer transition-colors hover:border-[var(--color-accent)] hover:bg-[var(--color-surface-elevated)]',
      )}
    >
      <div className="flex items-start justify-between">
        <div className="min-w-0 flex-1">
          <p className="text-xs font-medium uppercase tracking-wider text-[var(--color-text-secondary)]">
            {title}
          </p>
          <p
            className={clsx('mt-2 truncate font-bold text-[var(--color-text-primary)]', valueSize)}
            title={String(value)}
          >
            {displayValue}
          </p>
          {subtitle && <p className="mt-1 text-xs text-[var(--color-text-muted)]">{subtitle}</p>}
          {trend && <TrendBadge value={trend.value} isPositive={trend.isPositive} />}
        </div>
        {Icon && (
          <div className={clsx('rounded-lg p-2', iconColors.iconBg)}>
            <Icon className={clsx('h-5 w-5', iconColors.icon)} />
          </div>
        )}
        {interactive && (
          <ArrowRight
            className="ml-2 h-4 w-4 self-center text-[var(--color-text-muted)]"
            aria-hidden="true"
          />
        )}
      </div>
    </div>
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
  scrollToId,
}: MetricCardProps) {
  const isNumeric = typeof value === 'number'
  const body = (
    <CardBody
      title={title}
      value={value}
      displayValue={isNumeric ? value.toLocaleString() : value}
      valueSize={isNumeric ? 'text-2xl' : 'text-base'}
      subtitle={subtitle}
      Icon={Icon}
      iconColors={colorClasses[color]}
      trend={trend}
      interactive={Boolean(href || scrollToId)}
    />
  )

  if (href) {
    return (
      <Link
        to={href}
        aria-label={`View ${title} details`}
        className="rounded-lg focus:outline-none focus:ring-2 focus:ring-[var(--color-accent)] focus:ring-offset-2"
      >
        {body}
      </Link>
    )
  }

  if (scrollToId) {
    return (
      <button
        type="button"
        onClick={() => scrollToElement(scrollToId)}
        aria-label={`Jump to ${title} section`}
        className="block w-full rounded-lg text-left focus:outline-none focus:ring-2 focus:ring-[var(--color-accent)] focus:ring-offset-2"
      >
        {body}
      </button>
    )
  }

  return body
}
