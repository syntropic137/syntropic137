import { Clock, Coins, Wrench, Zap } from 'lucide-react'
import { MetricCard } from '../../components'
import type { SessionResponse } from '../../types'
import { formatDurationSeconds } from '../../utils/formatters'
import { TOOL_EVENT_TYPES } from './sessionConstants'

export function SessionMetrics({
  session,
  now,
}: {
  session: SessionResponse
  now: number
}) {
  const toolCallCount = session.operations.filter(op =>
    TOOL_EVENT_TYPES.includes(op.operation_type as typeof TOOL_EVENT_TYPES[number])
  ).length

  const durationValue =
    session.status === 'running' && session.started_at
      ? formatDurationSeconds((now - new Date(session.started_at).getTime()) / 1000)
      : formatDurationSeconds(session.duration_seconds)

  return (
    <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-5">
      <MetricCard
        title="Input Tokens"
        value={session.input_tokens.toLocaleString()}
        icon={Zap}
        color="accent"
      />
      <MetricCard
        title="Output Tokens"
        value={session.output_tokens.toLocaleString()}
        icon={Zap}
        color="accent"
      />
      <MetricCard
        title="Tool Calls"
        value={toolCallCount.toString()}
        icon={Wrench}
        color="default"
      />
      <MetricCard
        title="Total Cost"
        value={`$${Number(session.total_cost_usd).toFixed(4)}`}
        icon={Coins}
        color="warning"
      />
      <MetricCard
        title="Duration"
        value={durationValue}
        icon={Clock}
        color="default"
      />
    </div>
  )
}
