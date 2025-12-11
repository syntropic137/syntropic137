import { clsx } from 'clsx'
import {
  Activity,
  ArrowLeft,
  Ban,
  Brain,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  Clock,
  Coins,
  Cpu,
  MessageSquare,
  Play,
  Terminal,
  Wrench,
  XCircle,
  Zap,
} from 'lucide-react'
import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'

import { getSession, getToolTimeline, subscribeToEvents, type ToolExecution, type ToolTimelineResponse } from '../api/client'
import { Card, CardContent, CardHeader, EmptyState, MetricCard, PageLoader, StatusBadge } from '../components'
import type { OperationInfo, SessionResponse } from '../types'

// Icons for tool execution status (from ToolTimelineProjection)
const toolStatusIcons: Record<string, typeof Activity> = {
  started: Play,
  completed: Terminal,
  blocked: Ban,
}

const toolStatusColors: Record<string, string> = {
  started: 'text-amber-400 bg-amber-500/10',
  completed: 'text-emerald-400 bg-emerald-500/10',
  blocked: 'text-red-400 bg-red-500/10',
}

// Icons for operation types (legacy - for non-tool operations)
const operationIcons: Record<string, typeof Activity> = {
  // New v2 types
  message_request: MessageSquare,
  message_response: MessageSquare,
  tool_started: Play,
  tool_completed: Terminal,
  tool_blocked: XCircle,
  thinking: Brain,
  error: XCircle,
  // Legacy types (v1 backward compat)
  agent_request: MessageSquare,
  agent_response: MessageSquare,
  tool_use: Wrench,
  tool_execution: Wrench,
  tool_result: Terminal,
  validation: CheckCircle2,
}

// Colors for operation types
const operationColors: Record<string, string> = {
  // New v2 types
  message_request: 'text-blue-400 bg-blue-500/10',
  message_response: 'text-indigo-400 bg-indigo-500/10',
  tool_started: 'text-amber-400 bg-amber-500/10',
  tool_completed: 'text-emerald-400 bg-emerald-500/10',
  tool_blocked: 'text-red-400 bg-red-500/10',
  thinking: 'text-purple-400 bg-purple-500/10',
  error: 'text-red-400 bg-red-500/10',
  // Legacy types
  agent_request: 'text-blue-400 bg-blue-500/10',
  agent_response: 'text-indigo-400 bg-indigo-500/10',
  tool_use: 'text-amber-400 bg-amber-500/10',
  tool_execution: 'text-amber-400 bg-amber-500/10',
  tool_result: 'text-emerald-400 bg-emerald-500/10',
  validation: 'text-green-400 bg-green-500/10',
}

function formatTime(timestamp: string): string {
  return new Date(timestamp).toLocaleTimeString('en-US', {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
  })
}

function formatDuration(seconds: number | null): string {
  if (seconds === null) return '-'
  if (seconds < 1) return `${Math.round(seconds * 1000)}ms`
  if (seconds < 60) return `${seconds.toFixed(1)}s`
  return `${Math.floor(seconds / 60)}m ${Math.round(seconds % 60)}s`
}

// Component for expandable tool execution details (from ToolTimelineProjection)
function ToolExecutionDetails({ tool }: { tool: ToolExecution }) {
  const [expanded, setExpanded] = useState(false)

  const hasDetails = tool.tool_output || tool.tool_input || tool.block_reason

  if (!hasDetails) return null

  return (
    <div className="mt-2">
      <button
        onClick={() => setExpanded(!expanded)}
        className="flex items-center gap-1 text-xs text-[var(--color-text-muted)] hover:text-[var(--color-text-secondary)]"
      >
        {expanded ? <ChevronDown className="h-3 w-3" /> : <ChevronRight className="h-3 w-3" />}
        {expanded ? 'Hide details' : 'Show details'}
      </button>
      {expanded && (
        <div className="mt-2 rounded-lg bg-[var(--color-surface)] p-3 text-xs">
          {tool.tool_input && (
            <div className="mb-2">
              <span className="font-medium text-[var(--color-text-secondary)]">Input:</span>
              <pre className="mt-1 overflow-x-auto whitespace-pre-wrap text-[var(--color-text-muted)] font-mono">
                {JSON.stringify(tool.tool_input, null, 2)}
              </pre>
            </div>
          )}
          {tool.tool_output && (
            <div className="mb-2">
              <span className="font-medium text-[var(--color-text-secondary)]">Output:</span>
              <pre className="mt-1 max-h-48 overflow-auto whitespace-pre-wrap text-[var(--color-text-muted)] font-mono">
                {tool.tool_output}
              </pre>
            </div>
          )}
          {tool.block_reason && (
            <div className="mb-2">
              <span className="font-medium text-red-400">Blocked:</span>
              <pre className="mt-1 whitespace-pre-wrap text-[var(--color-text-muted)]">
                {tool.block_reason}
              </pre>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

// Component for expandable operation details (legacy - for non-tool operations)
function OperationDetails({ op }: { op: OperationInfo }) {
  const [expanded, setExpanded] = useState(false)

  const hasDetails = op.tool_output || op.tool_input || op.message_content || op.thinking_content

  if (!hasDetails) return null

  return (
    <div className="mt-2">
      <button
        onClick={() => setExpanded(!expanded)}
        className="flex items-center gap-1 text-xs text-[var(--color-text-muted)] hover:text-[var(--color-text-secondary)]"
      >
        {expanded ? <ChevronDown className="h-3 w-3" /> : <ChevronRight className="h-3 w-3" />}
        {expanded ? 'Hide details' : 'Show details'}
      </button>
      {expanded && (
        <div className="mt-2 rounded-lg bg-[var(--color-surface)] p-3 text-xs">
          {op.tool_input && (
            <div className="mb-2">
              <span className="font-medium text-[var(--color-text-secondary)]">Input:</span>
              <pre className="mt-1 overflow-x-auto whitespace-pre-wrap text-[var(--color-text-muted)] font-mono">
                {JSON.stringify(op.tool_input, null, 2)}
              </pre>
            </div>
          )}
          {op.tool_output && (
            <div className="mb-2">
              <span className="font-medium text-[var(--color-text-secondary)]">Output:</span>
              <pre className="mt-1 max-h-48 overflow-auto whitespace-pre-wrap text-[var(--color-text-muted)] font-mono">
                {op.tool_output}
              </pre>
            </div>
          )}
          {op.message_content && (
            <div className="mb-2">
              <span className="font-medium text-[var(--color-text-secondary)]">
                Message ({op.message_role}):
              </span>
              <pre className="mt-1 max-h-48 overflow-auto whitespace-pre-wrap text-[var(--color-text-muted)]">
                {op.message_content}
              </pre>
            </div>
          )}
          {op.thinking_content && (
            <div>
              <span className="font-medium text-[var(--color-text-secondary)]">Thinking:</span>
              <pre className="mt-1 max-h-48 overflow-auto whitespace-pre-wrap text-[var(--color-text-muted)]">
                {op.thinking_content}
              </pre>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

export function SessionDetail() {
  const { sessionId } = useParams<{ sessionId: string }>()
  const [session, setSession] = useState<SessionResponse | null>(null)
  const [toolTimeline, setToolTimeline] = useState<ToolTimelineResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!sessionId) return

    let cancelled = false

    // Fetch both session and tool timeline in parallel
    Promise.all([
      getSession(sessionId),
      getToolTimeline(sessionId).catch(() => null), // Tool timeline may not exist yet
    ])
      .then(([sessionData, toolData]) => {
        if (!cancelled) {
          setSession(sessionData)
          setToolTimeline(toolData)
        }
      })
      .catch((err) => { if (!cancelled) setError(err.message) })
      .finally(() => { if (!cancelled) setLoading(false) })

    return () => { cancelled = true }
  }, [sessionId])

  // Subscribe to SSE for real-time tool updates
  useEffect(() => {
    if (!sessionId || !session) return

    const unsubscribe = subscribeToEvents((event) => {
      // Only handle tool events for this session
      const eventSessionId = event.session_id || event.execution_id
      if (!eventSessionId || eventSessionId !== session.execution_id) return

      if (event.event_type === 'tool_execution_started') {
        const toolUseId = event.tool_use_id ?? ''
        const toolName = event.tool_name ?? 'unknown'
        setToolTimeline((prev) => {
          if (!prev) {
            return {
              session_id: sessionId,
              executions: [{
                event_id: `sse-${toolUseId}-started`,
                session_id: sessionId,
                tool_name: toolName,
                tool_use_id: toolUseId,
                status: 'started' as const,
                started_at: event.timestamp,
                tool_input: event.tool_input,
              }],
              total_executions: 1,
              completed_count: 0,
              blocked_count: 0,
              success_rate: null,
            }
          }
          // Check if this tool_use_id already exists
          const exists = prev.executions.some(e => e.tool_use_id === toolUseId)
          if (exists) return prev

          return {
            ...prev,
            executions: [...prev.executions, {
              event_id: `sse-${toolUseId}-started`,
              session_id: sessionId,
              tool_name: toolName,
              tool_use_id: toolUseId,
              status: 'started' as const,
              started_at: event.timestamp,
              tool_input: event.tool_input,
            }],
            total_executions: prev.total_executions + 1,
          }
        })
      } else if (event.event_type === 'tool_execution_completed') {
        const toolUseId = event.tool_use_id ?? ''
        setToolTimeline((prev) => {
          if (!prev) return prev
          return {
            ...prev,
            executions: prev.executions.map(e =>
              e.tool_use_id === toolUseId
                ? {
                  ...e,
                  status: 'completed' as const,
                  completed_at: event.timestamp,
                  duration_ms: event.duration_ms,
                  success: event.success,
                }
                : e
            ),
            completed_count: prev.completed_count + 1,
            success_rate: event.success
              ? (prev.success_rate ?? 0) + (1 / (prev.completed_count + 1))
              : prev.success_rate,
          }
        })
      } else if (event.event_type === 'tool_blocked') {
        const toolUseId = event.tool_use_id ?? ''
        const toolName = event.tool_name ?? 'unknown'
        setToolTimeline((prev) => {
          if (!prev) {
            return {
              session_id: sessionId,
              executions: [{
                event_id: `sse-${toolUseId}-blocked`,
                session_id: sessionId,
                tool_name: toolName,
                tool_use_id: toolUseId,
                status: 'blocked' as const,
                started_at: event.timestamp,
                block_reason: event.reason,
              }],
              total_executions: 1,
              completed_count: 0,
              blocked_count: 1,
              success_rate: null,
            }
          }
          return {
            ...prev,
            executions: [...prev.executions, {
              event_id: `sse-${toolUseId}-blocked`,
              session_id: sessionId,
              tool_name: toolName,
              tool_use_id: toolUseId,
              status: 'blocked' as const,
              started_at: event.timestamp,
              block_reason: event.reason,
            }],
            total_executions: prev.total_executions + 1,
            blocked_count: prev.blocked_count + 1,
          }
        })
      }
    })

    return () => unsubscribe()
    // eslint-disable-next-line react-hooks/exhaustive-deps -- Only re-subscribe when execution_id changes
  }, [sessionId, session?.execution_id])

  if (loading) return <PageLoader />

  if (error || !session) {
    return (
      <Card>
        <EmptyState
          icon={Activity}
          title="Session not found"
          description={error || `Could not find session with ID: ${sessionId}`}
        />
      </Card>
    )
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div>
        <Link
          to="/sessions"
          className="inline-flex items-center gap-1 text-sm text-[var(--color-text-secondary)] hover:text-[var(--color-text-primary)]"
        >
          <ArrowLeft className="h-4 w-4" />
          Back to Sessions
        </Link>
        <div className="mt-4 flex items-start justify-between">
          <div className="flex items-start gap-4">
            <div className="flex h-12 w-12 items-center justify-center rounded-xl bg-gradient-to-br from-emerald-500/20 to-teal-500/20">
              <Activity className="h-6 w-6 text-emerald-400" />
            </div>
            <div>
              <div className="flex items-center gap-3">
                <h1 className="font-mono text-xl font-bold text-[var(--color-text-primary)]">
                  {session.id.slice(0, 16)}...
                </h1>
                <StatusBadge status={session.status} size="lg" pulse />
              </div>
              <div className="mt-2 flex items-center gap-4 text-sm text-[var(--color-text-secondary)]">
                {session.workflow_id && (
                  <Link
                    to={`/workflows/${session.workflow_id}`}
                    className="hover:text-[var(--color-accent)]"
                  >
                    Workflow: {session.workflow_id.slice(0, 8)}...
                  </Link>
                )}
                {session.phase_id && <span>Phase: {session.phase_id}</span>}
              </div>
              <div className="mt-1 flex items-center gap-4 text-xs text-[var(--color-text-muted)]">
                <span className="flex items-center gap-1">
                  <Cpu className="h-3.5 w-3.5" />
                  {session.agent_provider}/{session.agent_model}
                </span>
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* Metrics */}
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
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
          title="Total Cost"
          value={`$${Number(session.total_cost_usd).toFixed(4)}`}
          icon={Coins}
          color="warning"
        />
        <MetricCard
          title="Duration"
          value={formatDuration(session.duration_seconds)}
          icon={Clock}
          color="default"
        />
      </div>

      {/* Error message if failed */}
      {session.error_message && (
        <Card className="border-red-500/30 bg-red-500/5">
          <CardContent className="flex items-start gap-3">
            <XCircle className="h-5 w-5 text-red-400 flex-shrink-0 mt-0.5" />
            <div>
              <p className="text-sm font-medium text-red-400">Execution Error</p>
              <p className="mt-1 text-sm text-[var(--color-text-secondary)]">
                {session.error_message}
              </p>
            </div>
          </CardContent>
        </Card>
      )}

      {/* Tool Executions Timeline (from ToolTimelineProjection - ADR-018 Pattern 2) */}
      {toolTimeline && toolTimeline.executions.length > 0 && (
        <Card>
          <CardHeader
            title="Tool Executions"
            subtitle={`${toolTimeline.total_executions} tools used • ${toolTimeline.success_rate !== null ? `${Math.round(toolTimeline.success_rate * 100)}% success rate` : 'N/A'}`}
          />
          <CardContent noPadding>
            <div className="relative">
              {/* Timeline line */}
              <div className="absolute left-8 top-0 bottom-0 w-px bg-[var(--color-border)]" />

              {/* Tool executions - sorted by time descending (latest first) */}
              <div className="space-y-0">
                {[...toolTimeline.executions]
                  .sort((a, b) => new Date(b.started_at).getTime() - new Date(a.started_at).getTime())
                  .map((tool, idx) => {
                    const Icon = toolStatusIcons[tool.status] ?? Wrench
                    const color = toolStatusColors[tool.status] ?? 'text-[var(--color-text-secondary)] bg-[var(--color-surface-elevated)]'
                    const [textColor, bgColor] = color.split(' ')

                    return (
                      <div
                        key={tool.event_id || `${tool.tool_use_id}-${idx}`}
                        className="relative flex items-start gap-4 px-4 py-3 hover:bg-[var(--color-surface-elevated)] transition-colors animate-fade-in"
                        style={{ animationDelay: `${idx * 30}ms` }}
                      >
                        {/* Icon */}
                        <div className={clsx('relative z-10 flex h-8 w-8 items-center justify-center rounded-lg', bgColor)}>
                          <Icon className={clsx('h-4 w-4', textColor)} />
                        </div>

                        {/* Content */}
                        <div className="flex-1 min-w-0">
                          <div className="flex items-center gap-3">
                            <span className="text-sm font-medium text-[var(--color-text-primary)]">
                              {tool.tool_name}
                            </span>
                            {tool.status === 'completed' && (
                              tool.success ? (
                                <CheckCircle2 className="h-3.5 w-3.5 text-emerald-400" />
                              ) : (
                                <XCircle className="h-3.5 w-3.5 text-red-400" />
                              )
                            )}
                            {tool.status === 'blocked' && (
                              <Ban className="h-3.5 w-3.5 text-red-400" />
                            )}
                            {tool.status === 'started' && (
                              <span className="flex h-2 w-2 rounded-full bg-amber-400 animate-pulse" />
                            )}
                            <span className="text-xs text-[var(--color-text-muted)]">
                              {formatTime(tool.started_at)}
                            </span>
                          </div>

                          {/* Summary details */}
                          <div className="mt-1 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-[var(--color-text-secondary)]">
                            <span className="capitalize px-1.5 py-0.5 rounded bg-[var(--color-surface)] text-[var(--color-text-muted)]">
                              {tool.status}
                            </span>
                            {tool.duration_ms !== undefined && (
                              <span className="flex items-center gap-1">
                                <Clock className="h-3 w-3" />
                                {tool.duration_ms < 1000 ? `${tool.duration_ms}ms` : `${(tool.duration_ms / 1000).toFixed(1)}s`}
                              </span>
                            )}
                            <span className="font-mono text-[10px] text-[var(--color-text-muted)]">
                              {tool.tool_use_id.slice(0, 12)}...
                            </span>
                          </div>

                          {/* Expandable details */}
                          <ToolExecutionDetails tool={tool} />
                        </div>
                      </div>
                    )
                  })}
              </div>
            </div>
          </CardContent>
        </Card>
      )}

      {/* Operations timeline (legacy - for message operations) */}
      <Card>
        <CardHeader
          title="Operations Timeline"
          subtitle={`${session.operations.length} operations recorded`}
        />
        <CardContent noPadding>
          {session.operations.length === 0 ? (
            <div className="p-8 text-center">
              <Activity className="mx-auto h-8 w-8 text-[var(--color-text-muted)]" />
              <p className="mt-2 text-sm text-[var(--color-text-muted)]">
                No operations recorded yet
              </p>
            </div>
          ) : (
            <div className="relative">
              {/* Timeline line */}
              <div className="absolute left-8 top-0 bottom-0 w-px bg-[var(--color-border)]" />

              {/* Operations - filter out tool ops, sort descending (latest first) */}
              <div className="space-y-0">
                {[...session.operations]
                  .filter(op => !toolTimeline || !['tool_started', 'tool_completed', 'tool_blocked', 'tool_use', 'tool_execution'].includes(op.operation_type))
                  .sort((a, b) => new Date(b.timestamp).getTime() - new Date(a.timestamp).getTime())
                  .map((op, idx) => {
                    const Icon = operationIcons[op.operation_type] ?? Activity
                    const color = operationColors[op.operation_type] ?? 'text-[var(--color-text-secondary)] bg-[var(--color-surface-elevated)]'
                    const [textColor, bgColor] = color.split(' ')

                    return (
                      <div
                        key={op.operation_id}
                        className="relative flex items-start gap-4 px-4 py-3 hover:bg-[var(--color-surface-elevated)] transition-colors animate-fade-in"
                        style={{ animationDelay: `${idx * 30}ms` }}
                      >
                        {/* Icon */}
                        <div className={clsx('relative z-10 flex h-8 w-8 items-center justify-center rounded-lg', bgColor)}>
                          <Icon className={clsx('h-4 w-4', textColor)} />
                        </div>

                        {/* Content */}
                        <div className="flex-1 min-w-0">
                          <div className="flex items-center gap-3">
                            <span className="text-sm font-medium text-[var(--color-text-primary)]">
                              {op.operation_type.split('_').map(w => w.charAt(0).toUpperCase() + w.slice(1)).join(' ')}
                            </span>
                            {op.success ? (
                              <CheckCircle2 className="h-3.5 w-3.5 text-emerald-400" />
                            ) : (
                              <XCircle className="h-3.5 w-3.5 text-red-400" />
                            )}
                            <span className="text-xs text-[var(--color-text-muted)]">
                              {formatTime(op.timestamp)}
                            </span>
                          </div>

                          {/* Summary details */}
                          <div className="mt-1 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-[var(--color-text-secondary)]">
                            {op.tool_name && (
                              <span className="flex items-center gap-1">
                                <Wrench className="h-3 w-3" />
                                {op.tool_name}
                              </span>
                            )}
                            {op.message_role && (
                              <span className="flex items-center gap-1">
                                <MessageSquare className="h-3 w-3" />
                                {op.message_role}
                              </span>
                            )}
                            {op.total_tokens !== null && op.total_tokens > 0 && (
                              <span className="flex items-center gap-1">
                                <Zap className="h-3 w-3" />
                                {op.total_tokens.toLocaleString()} tokens
                              </span>
                            )}
                            {op.duration_seconds !== null && (
                              <span className="flex items-center gap-1">
                                <Clock className="h-3 w-3" />
                                {formatDuration(op.duration_seconds)}
                              </span>
                            )}
                          </div>

                          {/* Expandable details */}
                          <OperationDetails op={op} />
                        </div>
                      </div>
                    )
                  })}
              </div>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
