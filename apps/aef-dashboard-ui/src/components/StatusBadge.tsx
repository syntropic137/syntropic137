import { clsx } from 'clsx'

interface StatusBadgeProps {
  status: string
  size?: 'sm' | 'md' | 'lg'
  pulse?: boolean
}

const statusColors: Record<string, { bg: string; text: string; ring: string }> = {
  pending: { bg: 'bg-slate-500/20', text: 'text-slate-400', ring: 'ring-slate-500/30' },
  in_progress: { bg: 'bg-blue-500/20', text: 'text-blue-400', ring: 'ring-blue-500/30' },
  running: { bg: 'bg-blue-500/20', text: 'text-blue-400', ring: 'ring-blue-500/30' },
  completed: { bg: 'bg-emerald-500/20', text: 'text-emerald-400', ring: 'ring-emerald-500/30' },
  failed: { bg: 'bg-red-500/20', text: 'text-red-400', ring: 'ring-red-500/30' },
  cancelled: { bg: 'bg-amber-500/20', text: 'text-amber-400', ring: 'ring-amber-500/30' },
  skipped: { bg: 'bg-slate-500/20', text: 'text-slate-400', ring: 'ring-slate-500/30' },
}

const sizeClasses = {
  sm: 'px-1.5 py-0.5 text-xs',
  md: 'px-2 py-1 text-xs',
  lg: 'px-3 py-1.5 text-sm',
}

export function StatusBadge({ status, size = 'md', pulse = false }: StatusBadgeProps) {
  const colors = statusColors[status] ?? statusColors.pending
  const isActive = status === 'running' || status === 'in_progress'

  return (
    <span
      className={clsx(
        'inline-flex items-center gap-1.5 rounded-full font-medium ring-1 ring-inset',
        colors.bg,
        colors.text,
        colors.ring,
        sizeClasses[size],
        pulse && isActive && 'animate-pulse-glow'
      )}
    >
      {isActive && (
        <span className="relative flex h-2 w-2">
          <span
            className={clsx(
              'absolute inline-flex h-full w-full animate-ping rounded-full opacity-75',
              status === 'running' ? 'bg-blue-400' : 'bg-blue-400'
            )}
          />
          <span
            className={clsx(
              'relative inline-flex h-2 w-2 rounded-full',
              status === 'running' ? 'bg-blue-500' : 'bg-blue-500'
            )}
          />
        </span>
      )}
      {status.replace('_', ' ')}
    </span>
  )
}
