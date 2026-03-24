import { Clock, DollarSign, MessageSquare, Zap } from 'lucide-react'
import type { SessionCost } from '../types'
import { formatCost, formatDuration, formatTokens } from '../utils/formatters'
import { ToolCostBreakdown } from './ToolCostBreakdown'

interface SessionCostCardProps {
  cost: SessionCost
  showBreakdown?: boolean
  showToolTokens?: boolean
  compact?: boolean
}

function CompactSessionCost({ cost }: { cost: SessionCost }) {
  return (
    <div className="flex items-center gap-4 text-sm">
      <div className="flex items-center gap-1.5">
        <DollarSign className="h-4 w-4 text-emerald-400" />
        <span className="font-medium text-[var(--color-text-primary)]">
          {formatCost(cost.total_cost_usd)}
        </span>
      </div>
      <div className="flex items-center gap-1.5 text-[var(--color-text-muted)]">
        <MessageSquare className="h-3.5 w-3.5" />
        <span>{formatTokens(cost.total_tokens)} tokens</span>
      </div>
      <div className="flex items-center gap-1.5 text-[var(--color-text-muted)]">
        <Zap className="h-3.5 w-3.5" />
        <span>{cost.tool_calls} tools</span>
      </div>
    </div>
  )
}

function SessionMetricsGrid({ cost }: { cost: SessionCost }) {
  return (
    <div className="grid grid-cols-4 gap-2 py-3 border-t border-[var(--color-border)]">
      <div className="text-center">
        <p className="text-lg font-semibold text-[var(--color-text-primary)]">
          {formatTokens(cost.input_tokens)}
        </p>
        <p className="text-xs text-[var(--color-text-muted)]">Input</p>
      </div>
      <div className="text-center">
        <p className="text-lg font-semibold text-[var(--color-text-primary)]">
          {formatTokens(cost.output_tokens)}
        </p>
        <p className="text-xs text-[var(--color-text-muted)]">Output</p>
      </div>
      <div className="text-center">
        <p className="text-lg font-semibold text-[var(--color-text-primary)]">
          {cost.tool_calls}
        </p>
        <p className="text-xs text-[var(--color-text-muted)]">Tools</p>
      </div>
      <div className="text-center">
        <p className="text-lg font-semibold text-[var(--color-text-primary)]">
          {cost.turns}
        </p>
        <p className="text-xs text-[var(--color-text-muted)]">Turns</p>
      </div>
    </div>
  )
}

function SessionBreakdowns({ cost }: { cost: SessionCost }) {
  const hasModelBreakdown = Object.keys(cost.cost_by_model).length > 0
  const hasToolBreakdown = Object.keys(cost.cost_by_tool).length > 0

  if (!hasModelBreakdown && !hasToolBreakdown) return null

  return (
    <div className="mt-4 pt-4 border-t border-[var(--color-border)]">
      {hasModelBreakdown && (
        <div className="mb-3">
          <p className="text-xs font-medium text-[var(--color-text-secondary)] mb-2">
            Cost by Model
          </p>
          <div className="space-y-1">
            {Object.entries(cost.cost_by_model).map(([model, modelCost]) => (
              <div key={model} className="flex justify-between text-sm">
                <span className="text-[var(--color-text-muted)] truncate">{model}</span>
                <span className="text-[var(--color-text-primary)] font-medium">
                  ${parseFloat(modelCost).toFixed(4)}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}

      {hasToolBreakdown && (
        <div>
          <p className="text-xs font-medium text-[var(--color-text-secondary)] mb-2">
            Cost by Tool
          </p>
          <div className="space-y-1">
            {Object.entries(cost.cost_by_tool).map(([tool, toolCost]) => (
              <div key={tool} className="flex justify-between text-sm">
                <span className="text-[var(--color-text-muted)] truncate">{tool}</span>
                <span className="text-[var(--color-text-primary)] font-medium">
                  ${parseFloat(toolCost).toFixed(4)}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

export function SessionCostCard({
  cost,
  showBreakdown = false,
  showToolTokens = false,
  compact = false,
}: SessionCostCardProps) {
  const hasToolTokens = cost.tokens_by_tool && Object.keys(cost.tokens_by_tool).length > 0

  if (compact) {
    return <CompactSessionCost cost={cost} />
  }

  return (
    <div className="rounded-lg border border-[var(--color-border)] bg-[var(--color-surface)] p-4">
      <div className="flex items-center justify-between mb-4">
        <h3 className="text-sm font-medium text-[var(--color-text-secondary)]">Session Cost</h3>
        {cost.is_finalized && (
          <span className="text-xs px-2 py-0.5 rounded bg-emerald-500/10 text-emerald-400">
            Finalized
          </span>
        )}
      </div>

      {/* Main cost display */}
      <div className="flex items-baseline gap-2 mb-4">
        <span className="text-3xl font-bold text-[var(--color-text-primary)]">
          {formatCost(cost.total_cost_usd)}
        </span>
        <span className="text-sm text-[var(--color-text-muted)]">USD</span>
      </div>

      {/* Cost breakdown */}
      <div className="grid grid-cols-2 gap-4 mb-4">
        <div>
          <p className="text-xs text-[var(--color-text-muted)]">Token Cost</p>
          <p className="text-sm font-medium text-[var(--color-text-primary)]">
            {formatCost(cost.token_cost_usd)}
          </p>
        </div>
        <div>
          <p className="text-xs text-[var(--color-text-muted)]">Compute Cost</p>
          <p className="text-sm font-medium text-[var(--color-text-primary)]">
            {formatCost(cost.compute_cost_usd)}
          </p>
        </div>
      </div>

      <SessionMetricsGrid cost={cost} />

      {/* Duration */}
      {cost.duration_ms > 0 && (
        <div className="flex items-center gap-2 mt-3 text-sm text-[var(--color-text-muted)]">
          <Clock className="h-4 w-4" />
          <span>Duration: {formatDuration(cost.duration_ms)}</span>
        </div>
      )}

      {/* Model/Tool breakdown */}
      {showBreakdown && <SessionBreakdowns cost={cost} />}

      {/* Tool Token Attribution */}
      {showToolTokens && hasToolTokens && (
        <div className="mt-4 pt-4 border-t border-[var(--color-border)]">
          <ToolCostBreakdown
            tokensByTool={cost.tokens_by_tool}
            costByToolTokens={cost.cost_by_tool_tokens}
          />
        </div>
      )}
    </div>
  )
}
