import { Clock, Coins, Wrench } from 'lucide-react'
import { MetricCard, ModelBreakdown } from '../../components'
import { TokenBreakdown } from '../../components/TokenBreakdown'
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

  const hasCostByModel = session.cost_by_model && Object.keys(session.cost_by_model).length > 0

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
        <MetricCard
          title="Total Cost"
          value={`$${Number(session.total_cost_usd).toFixed(4)}`}
          icon={Coins}
          color="warning"
          scrollToId={hasCostByModel ? 'cost-by-model' : undefined}
        />
        <MetricCard title="Duration" value={durationValue} icon={Clock} color="default" />
        <MetricCard
          title="Tool Calls"
          value={toolCallCount.toString()}
          icon={Wrench}
          color="default"
          scrollToId="operations-timeline"
        />
      </div>
      <section id="token-breakdown">
        <TokenBreakdown
          inputTokens={session.input_tokens}
          outputTokens={session.output_tokens}
          cacheCreationTokens={session.cache_creation_tokens ?? 0}
          cacheReadTokens={session.cache_read_tokens ?? 0}
        />
      </section>
      {hasCostByModel && (
        <section id="cost-by-model">
          <ModelBreakdown costByModel={session.cost_by_model} />
        </section>
      )}
    </div>
  )
}
