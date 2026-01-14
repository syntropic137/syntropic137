import { useState } from 'react'
import type { SubagentRecord } from '../types'
import { formatDuration } from '../utils/formatters'

interface SubagentCardProps {
  subagent: SubagentRecord
  isExpanded?: boolean
}

export function SubagentCard({ subagent, isExpanded: initialExpanded = false }: SubagentCardProps) {
  const [isExpanded, setIsExpanded] = useState(initialExpanded)

  const toolCount = Object.values(subagent.tools_used).reduce((sum, count) => sum + count, 0)
  // formatDuration expects seconds, duration_ms is milliseconds
  const duration = subagent.duration_ms ? formatDuration(subagent.duration_ms / 1000) : '—'

  return (
    <div className="border border-slate-700 rounded-lg bg-slate-800/50 overflow-hidden">
      {/* Header - always visible */}
      <button
        onClick={() => setIsExpanded(!isExpanded)}
        className="w-full px-4 py-3 flex items-center justify-between hover:bg-slate-700/30 transition-colors"
      >
        <div className="flex items-center gap-3">
          {/* Status indicator */}
          <div
            className={`w-2 h-2 rounded-full ${
              subagent.success ? 'bg-emerald-500' : 'bg-red-500'
            }`}
          />
          {/* Agent name */}
          <span className="font-medium text-slate-200 truncate max-w-[200px]">
            {subagent.agent_name || 'Unnamed Subagent'}
          </span>
        </div>

        <div className="flex items-center gap-4 text-sm text-slate-400">
          {/* Tool count */}
          <span className="flex items-center gap-1">
            <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z" />
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
            </svg>
            {toolCount} tools
          </span>

          {/* Duration */}
          <span className="flex items-center gap-1">
            <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" />
            </svg>
            {duration}
          </span>

          {/* Expand icon */}
          <svg
            className={`w-4 h-4 transition-transform ${isExpanded ? 'rotate-180' : ''}`}
            fill="none"
            viewBox="0 0 24 24"
            stroke="currentColor"
          >
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
          </svg>
        </div>
      </button>

      {/* Expanded content */}
      {isExpanded && (
        <div className="px-4 pb-4 border-t border-slate-700">
          <div className="pt-3 space-y-3">
            {/* Tool breakdown */}
            {Object.keys(subagent.tools_used).length > 0 && (
              <div>
                <h4 className="text-xs font-medium text-slate-500 uppercase tracking-wider mb-2">
                  Tools Used
                </h4>
                <div className="flex flex-wrap gap-2">
                  {Object.entries(subagent.tools_used).map(([tool, count]) => (
                    <span
                      key={tool}
                      className="px-2 py-1 text-xs rounded bg-slate-700 text-slate-300"
                    >
                      {tool}: {count}
                    </span>
                  ))}
                </div>
              </div>
            )}

            {/* Metadata */}
            <div className="grid grid-cols-2 gap-2 text-xs">
              <div>
                <span className="text-slate-500">Started:</span>{' '}
                <span className="text-slate-300">
                  {subagent.started_at
                    ? new Date(subagent.started_at).toLocaleTimeString()
                    : '—'}
                </span>
              </div>
              <div>
                <span className="text-slate-500">Stopped:</span>{' '}
                <span className="text-slate-300">
                  {subagent.stopped_at
                    ? new Date(subagent.stopped_at).toLocaleTimeString()
                    : '—'}
                </span>
              </div>
              <div className="col-span-2">
                <span className="text-slate-500">ID:</span>{' '}
                <code className="text-slate-400 text-[10px]">
                  {subagent.subagent_tool_use_id}
                </code>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

interface SubagentListProps {
  subagents: SubagentRecord[]
  title?: string
}

export function SubagentList({ subagents, title = 'Subagents' }: SubagentListProps) {
  if (subagents.length === 0) {
    return null
  }

  return (
    <div className="space-y-3">
      <h3 className="text-sm font-medium text-slate-400 flex items-center gap-2">
        <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M17 20h5v-2a3 3 0 00-5.356-1.857M17 20H7m10 0v-2c0-.656-.126-1.283-.356-1.857M7 20H2v-2a3 3 0 015.356-1.857M7 20v-2c0-.656.126-1.283.356-1.857m0 0a5.002 5.002 0 019.288 0M15 7a3 3 0 11-6 0 3 3 0 016 0zm6 3a2 2 0 11-4 0 2 2 0 014 0zM7 10a2 2 0 11-4 0 2 2 0 014 0z" />
        </svg>
        {title} ({subagents.length})
      </h3>
      <div className="space-y-2">
        {subagents.map((subagent) => (
          <SubagentCard key={subagent.subagent_tool_use_id} subagent={subagent} />
        ))}
      </div>
    </div>
  )
}
