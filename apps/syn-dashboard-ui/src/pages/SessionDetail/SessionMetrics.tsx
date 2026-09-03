import { Clock, Coins, Wrench } from 'lucide-react'
import { MetricCard, ModelBreakdown } from '../../components'
import { TokenBreakdown } from '../../components/TokenBreakdown'
import type { SessionResponse } from '../../types'
import {
  formatCostWithCoverage,
  formatDurationSeconds,
  liveDurationSeconds,
} from '../../utils/formatters'
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

  // Same rule as the phase timeline: tick while running, but fall back to the
  // server's resolved value when the live reading is not measurable, so a
  // skewed or malformed started_at cannot render as a negative or "NaN".
  const durationValue = formatDurationSeconds(
    liveDurationSeconds(session.status === 'running', session.started_at, session.duration_seconds, now)
  )

  const hasCostByModel = session.cost_by_model && Object.keys(session.cost_by_model).length > 0

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
        <MetricCard
          title="Total Cost"
          value={formatCostWithCoverage(
            Number(session.total_cost_usd),
            session.unpriced_observation_count
          )}
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
