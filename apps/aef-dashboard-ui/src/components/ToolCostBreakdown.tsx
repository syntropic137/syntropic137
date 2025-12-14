import { clsx } from 'clsx'
import { Wrench } from 'lucide-react'
import { formatCost, formatTokens } from '../utils/formatters'

interface ToolCostBreakdownProps {
  tokensByTool: Record<string, number>
  costByToolTokens: Record<string, string>
  className?: string
  maxTools?: number
}

/**
 * Component to display per-tool token and cost breakdown.
 *
 * Shows a bar chart visualization of tokens consumed by each tool,
 * along with the estimated cost contribution.
 */
export function ToolCostBreakdown({
  tokensByTool,
  costByToolTokens,
  className,
  maxTools = 5,
}: ToolCostBreakdownProps) {
  // Sort tools by token count descending
  const sortedTools = Object.entries(tokensByTool)
    .sort(([, a], [, b]) => b - a)
    .slice(0, maxTools)

  if (sortedTools.length === 0) {
    return null
  }

  // Calculate max for bar width percentage
  const maxTokens = Math.max(...sortedTools.map(([, tokens]) => tokens))

  // Tool colors (consistent by tool name)
  const getToolColor = (toolName: string): string => {
    const colors: Record<string, string> = {
      Write: 'bg-blue-500',
      Read: 'bg-green-500',
      Shell: 'bg-orange-500',
      Grep: 'bg-purple-500',
      Glob: 'bg-pink-500',
      LS: 'bg-cyan-500',
      Search: 'bg-indigo-500',
      Edit: 'bg-yellow-500',
      Delete: 'bg-red-500',
    }
    return colors[toolName] || 'bg-gray-500'
  }

  return (
    <div className={clsx('space-y-3', className)}>
      <div className="flex items-center gap-2 text-sm font-medium text-gray-700">
        <Wrench className="h-4 w-4" />
        <span>Token Usage by Tool</span>
        <span className="text-xs text-gray-400">(estimated)</span>
      </div>

      <div className="space-y-2">
        {sortedTools.map(([toolName, tokens]) => {
          const cost = costByToolTokens[toolName]
          const widthPercent = (tokens / maxTokens) * 100

          return (
            <div key={toolName} className="space-y-1">
              <div className="flex items-center justify-between text-xs">
                <span className="font-medium text-gray-700">{toolName}</span>
                <div className="flex items-center gap-2 text-gray-500">
                  <span>{formatTokens(tokens)} tokens</span>
                  {cost && <span className="text-green-600">{formatCost(parseFloat(cost))}</span>}
                </div>
              </div>
              <div className="h-2 w-full rounded-full bg-gray-100">
                <div
                  className={clsx('h-full rounded-full transition-all duration-300', getToolColor(toolName))}
                  style={{ width: `${widthPercent}%` }}
                />
              </div>
            </div>
          )
        })}
      </div>

      {Object.keys(tokensByTool).length > maxTools && (
        <div className="text-xs text-gray-400">
          +{Object.keys(tokensByTool).length - maxTools} more tools
        </div>
      )}
    </div>
  )
}
