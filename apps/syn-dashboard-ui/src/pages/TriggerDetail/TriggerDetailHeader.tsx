import { Zap } from 'lucide-react'
import type { TriggerDetail } from '../../api/triggers'

const statusColors: Record<string, string> = {
  active: 'bg-green-500/10 text-green-400 ring-green-500/30',
  paused: 'bg-yellow-500/10 text-yellow-400 ring-yellow-500/30',
  deleted: 'bg-red-500/10 text-red-400 ring-red-500/30',
}

export function TriggerDetailHeader({ trigger }: { trigger: TriggerDetail }) {
  return (
    <div className="flex items-start gap-4">
      <div className="flex h-12 w-12 items-center justify-center rounded-xl bg-gradient-to-br from-amber-500/20 to-orange-500/20">
        <Zap className="h-6 w-6 text-amber-400" />
      </div>
      <div>
        <div className="flex items-center gap-3">
          <h1 className="text-2xl font-bold text-[var(--color-text-primary)]">
            {trigger.name}
          </h1>
          <span
            className={`inline-flex items-center rounded-full px-2 py-1 text-xs font-medium ring-1 ring-inset ${
              statusColors[trigger.status] ?? 'bg-gray-500/10 text-gray-400 ring-gray-500/30'
            }`}
          >
            {trigger.status}
          </span>
        </div>
        <div className="mt-2 flex items-center gap-4 text-xs text-[var(--color-text-muted)]">
          <span className="font-mono">{trigger.trigger_id}</span>
          <span>Event: {trigger.event}</span>
          {trigger.repository && (
            <>
              <span>&bull;</span>
              <span>{trigger.repository}</span>
            </>
          )}
        </div>
      </div>
    </div>
  )
}
