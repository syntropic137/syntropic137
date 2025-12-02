import { clsx } from 'clsx'
import type { ReactNode } from 'react'

interface CardProps {
  children: ReactNode
  className?: string
  hover?: boolean
  onClick?: () => void
}

export function Card({ children, className, hover = false, onClick }: CardProps) {
  return (
    <div
      className={clsx(
        'rounded-lg border border-[var(--color-border)] bg-[var(--color-surface)]',
        'transition-all duration-200',
        hover && 'cursor-pointer hover:border-[var(--color-accent)]/50 hover:bg-[var(--color-surface-elevated)]',
        className
      )}
      onClick={onClick}
      role={onClick ? 'button' : undefined}
      tabIndex={onClick ? 0 : undefined}
    >
      {children}
    </div>
  )
}

interface CardHeaderProps {
  title: string
  subtitle?: string
  action?: ReactNode
}

export function CardHeader({ title, subtitle, action }: CardHeaderProps) {
  return (
    <div className="flex items-center justify-between border-b border-[var(--color-border)] p-4">
      <div>
        <h3 className="text-sm font-semibold text-[var(--color-text-primary)]">{title}</h3>
        {subtitle && (
          <p className="mt-0.5 text-xs text-[var(--color-text-secondary)]">{subtitle}</p>
        )}
      </div>
      {action}
    </div>
  )
}

interface CardContentProps {
  children: ReactNode
  className?: string
  noPadding?: boolean
}

export function CardContent({ children, className, noPadding = false }: CardContentProps) {
  return (
    <div className={clsx(!noPadding && 'p-4', className)}>
      {children}
    </div>
  )
}

