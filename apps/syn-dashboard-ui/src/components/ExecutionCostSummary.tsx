import { clsx } from 'clsx'
import { Clock, DollarSign, Layers, MessageSquare, TrendingUp, Zap } from 'lucide-react'
import type { ExecutionCost } from '../types'
import { formatCost, formatDuration, formatTokens } from '../utils/formatters'

interface ExecutionCostSummaryProps {
  cost: ExecutionCost
  showBreakdown?: boolean
}

export function ExecutionCostSummary({ cost, showBreakdown = true }: ExecutionCostSummaryProps) {
  const hasPhaseBreakdown = Object.keys(cost.cost_by_phase).length > 0
  const hasModelBreakdown = Object.keys(cost.cost_by_model).length > 0

  return (
    <div className="rounded-lg border border-[var(--color-border)] bg-[var(--color-surface)]">
      {/* Header */}
      <div className="p-4 border-b border-[var(--color-border)]">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <div className="p-2 rounded-lg bg-emerald-500/10">
              <DollarSign className="h-5 w-5 text-emerald-400" />
            </div>
            <div>
              <h3 className="text-sm font-medium text-[var(--color-text-secondary)]">
                Execution Cost
              </h3>
              <p className="text-2xl font-bold text-[var(--color-text-primary)]">
                {formatCost(cost.total_cost_usd)}
              </p>
            </div>
          </div>
          <div className="text-right">
            <p className="text-xs text-[var(--color-text-muted)]">Sessions</p>
            <p className="text-lg font-semibold text-[var(--color-text-primary)]">
              {cost.session_count}
            </p>
          </div>
        </div>
      </div>

      {/* Cost breakdown row */}
      <div className="grid grid-cols-2 gap-4 p-4 border-b border-[var(--color-border)]">
        <div className="flex items-center gap-3">
          <div className="p-1.5 rounded bg-indigo-500/10">
            <MessageSquare className="h-4 w-4 text-indigo-400" />
          </div>
          <div>
            <p className="text-xs text-[var(--color-text-muted)]">Token Cost</p>
            <p className="text-sm font-medium text-[var(--color-text-primary)]">
              {formatCost(cost.token_cost_usd)}
            </p>
          </div>
        </div>
        <div className="flex items-center gap-3">
          <div className="p-1.5 rounded bg-amber-500/10">
            <Zap className="h-4 w-4 text-amber-400" />
          </div>
          <div>
            <p className="text-xs text-[var(--color-text-muted)]">Compute Cost</p>
            <p className="text-sm font-medium text-[var(--color-text-primary)]">
              {formatCost(cost.compute_cost_usd)}
            </p>
          </div>
        </div>
      </div>

      {/* Metrics grid */}
      <div className="grid grid-cols-4 gap-2 p-4 border-b border-[var(--color-border)]">
        <div className="text-center">
          <p className="text-lg font-semibold text-[var(--color-text-primary)]">
            {formatTokens(cost.input_tokens)}
          </p>
          <p className="text-xs text-[var(--color-text-muted)]">Input Tokens</p>
        </div>
        <div className="text-center">
          <p className="text-lg font-semibold text-[var(--color-text-primary)]">
            {formatTokens(cost.output_tokens)}
          </p>
          <p className="text-xs text-[var(--color-text-muted)]">Output Tokens</p>
        </div>
        <div className="text-center">
          <p className="text-lg font-semibold text-[var(--color-text-primary)]">
            {cost.tool_calls}
          </p>
          <p className="text-xs text-[var(--color-text-muted)]">Tool Calls</p>
        </div>
        <div className="text-center">
          <p className="text-lg font-semibold text-[var(--color-text-primary)]">
            {cost.turns}
          </p>
          <p className="text-xs text-[var(--color-text-muted)]">Turns</p>
        </div>
      </div>

      {/* Duration */}
      {cost.duration_ms > 0 && (
        <div className="flex items-center gap-2 px-4 py-3 border-b border-[var(--color-border)] text-sm text-[var(--color-text-muted)]">
          <Clock className="h-4 w-4" />
          <span>Total Duration: {formatDuration(cost.duration_ms)}</span>
        </div>
      )}

      {/* Breakdowns */}
      {showBreakdown && (hasPhaseBreakdown || hasModelBreakdown) && (
        <div className="p-4 space-y-4">
          {/* Phase breakdown */}
          {hasPhaseBreakdown && (
            <div>
              <div className="flex items-center gap-2 mb-2">
                <Layers className="h-4 w-4 text-[var(--color-text-secondary)]" />
                <p className="text-xs font-medium text-[var(--color-text-secondary)]">
                  Cost by Phase
                </p>
              </div>
              <div className="space-y-2">
                {Object.entries(cost.cost_by_phase).map(([phase, phaseCost]) => {
                  const costValue = parseFloat(phaseCost)
                  const percentage = cost.total_cost_usd > 0
                    ? (costValue / cost.total_cost_usd) * 100
                    : 0

                  return (
                    <div key={phase} className="space-y-1">
                      <div className="flex justify-between text-sm">
                        <span className="text-[var(--color-text-muted)]">{phase}</span>
                        <span className="text-[var(--color-text-primary)] font-medium">
                          {formatCost(costValue)} ({percentage.toFixed(1)}%)
                        </span>
                      </div>
                      <div className="h-1.5 bg-[var(--color-surface-elevated)] rounded-full overflow-hidden">
                        <div
                          className="h-full bg-indigo-500 rounded-full transition-all"
                          style={{ width: `${percentage}%` }}
                        />
                      </div>
                    </div>
                  )
                })}
              </div>
            </div>
          )}

          {/* Model breakdown */}
          {hasModelBreakdown && (
            <div>
              <div className="flex items-center gap-2 mb-2">
                <TrendingUp className="h-4 w-4 text-[var(--color-text-secondary)]" />
                <p className="text-xs font-medium text-[var(--color-text-secondary)]">
                  Cost by Model
                </p>
              </div>
              <div className="space-y-1">
                {Object.entries(cost.cost_by_model)
                  .sort(([, a], [, b]) => parseFloat(b) - parseFloat(a))
                  .map(([model, modelCost]) => (
                    <div key={model} className="flex justify-between text-sm">
                      <span className="text-[var(--color-text-muted)] truncate flex-1">{model}</span>
                      <span className="text-[var(--color-text-primary)] font-medium ml-4">
                        {formatCost(parseFloat(modelCost))}
                      </span>
                    </div>
                  ))}
              </div>
            </div>
          )}
        </div>
      )}

      {/* Status */}
      <div className="px-4 py-3 bg-[var(--color-surface-elevated)] rounded-b-lg">
        <div className="flex items-center justify-between text-xs">
          <span className={clsx(
            'px-2 py-0.5 rounded font-medium',
            cost.is_complete
              ? 'bg-emerald-500/10 text-emerald-400'
              : 'bg-amber-500/10 text-amber-400'
          )}>
            {cost.is_complete ? 'Complete' : 'In Progress'}
          </span>
          {cost.started_at && (
            <span className="text-[var(--color-text-muted)]">
              Started: {new Date(cost.started_at).toLocaleString()}
            </span>
          )}
        </div>
      </div>
    </div>
  )
}
