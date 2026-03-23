import type { MetricsResponse } from '../types'
import { API_BASE, fetchJSON } from './base'

export async function getMetrics(workflowId?: string): Promise<MetricsResponse> {
  const query = workflowId ? `?workflow_id=${workflowId}` : ''
  return fetchJSON(`${API_BASE}/metrics${query}`)
}

export interface ToolExecution {
  event_id: string
  session_id: string
  tool_name: string
  tool_use_id: string
  status: 'started' | 'completed' | 'blocked'
  started_at: string
  completed_at?: string
  duration_ms?: number
  success?: boolean
  tool_input?: Record<string, unknown>
  tool_output?: string
  block_reason?: string
}

export interface ToolTimelineResponse {
  session_id: string
  executions: ToolExecution[]
  total_executions: number
  completed_count: number
  blocked_count: number
  success_rate: number | null
}

export async function getToolTimeline(
  sessionId: string,
  options?: { limit?: number; includeBlocked?: boolean }
): Promise<ToolTimelineResponse> {
  const searchParams = new URLSearchParams()
  if (options?.limit) searchParams.set('limit', String(options.limit))
  if (options?.includeBlocked !== undefined) {
    searchParams.set('include_blocked', String(options.includeBlocked))
  }

  const query = searchParams.toString()
  return fetchJSON(`${API_BASE}/observability/sessions/${sessionId}/tools${query ? `?${query}` : ''}`)
}

export interface TokenMetricsResponse {
  session_id: string
  total_input_tokens: number
  total_output_tokens: number
  total_tokens: number
  message_count: number
}

export async function getTokenMetrics(sessionId: string): Promise<TokenMetricsResponse> {
  return fetchJSON(`${API_BASE}/observability/sessions/${sessionId}/tokens`)
}

export function getExecutionSSEUrl(executionId: string): string {
  return `${API_BASE}/sse/executions/${executionId}`
}

export async function getSSEHealth(): Promise<{
  status: string
  active_executions: number
  active_connections: number
}> {
  return fetchJSON(`${API_BASE}/sse/health`)
}

export interface ConversationLine {
  line_number: number
  raw: string
  parsed: Record<string, unknown> | null
  event_type: string | null
  tool_name: string | null
  content_preview: string | null
}

export interface ConversationLogResponse {
  session_id: string
  lines: ConversationLine[]
  total_lines: number
  metadata: Record<string, unknown> | null
}

export async function getConversationLog(
  sessionId: string,
  options?: { offset?: number; limit?: number }
): Promise<ConversationLogResponse> {
  const searchParams = new URLSearchParams()
  if (options?.offset !== undefined) searchParams.set('offset', String(options.offset))
  if (options?.limit !== undefined) searchParams.set('limit', String(options.limit))

  const query = searchParams.toString()
  return fetchJSON(`${API_BASE}/conversations/${sessionId}${query ? `?${query}` : ''}`)
}
