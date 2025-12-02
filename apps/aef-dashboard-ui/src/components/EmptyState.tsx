import type { LucideIcon } from 'lucide-react'
import { Inbox } from 'lucide-react'

interface EmptyStateProps {
  icon?: LucideIcon
  title: string
  description?: string
  action?: {
    label: string
    onClick: () => void
  }
}

export function EmptyState({
  icon: Icon = Inbox,
  title,
  description,
  action,
}: EmptyStateProps) {
  return (
    <div className="flex flex-col items-center justify-center py-12 text-center">
      <div className="rounded-full bg-[var(--color-surface-elevated)] p-4">
        <Icon className="h-8 w-8 text-[var(--color-text-muted)]" />
      </div>
      <h3 className="mt-4 text-sm font-medium text-[var(--color-text-primary)]">{title}</h3>
      {description && (
        <p className="mt-1 text-xs text-[var(--color-text-secondary)]">{description}</p>
      )}
      {action && (
        <button
          onClick={action.onClick}
          className="mt-4 rounded-md bg-[var(--color-accent)] px-3 py-1.5 text-xs font-medium text-white transition-colors hover:bg-[var(--color-accent-hover)]"
        >
          {action.label}
        </button>
      )}
    </div>
  )
}
