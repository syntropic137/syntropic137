import { clientConfig, request, seg } from '../client'
import type { components } from '../generated/api-types'
import type { MetricsResponse } from '../types'
import { cached } from '../keys'

export function getMetrics(workflowId?: string, signal?: AbortSignal): Promise<MetricsResponse> {
  return cached('getMetrics', [workflowId], (s) => request('/metrics', { query: { workflow_id: workflowId }, signal: s }), { signal, staleAfter: 'metrics' })
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

export function getToolTimeline(
  sessionId: string,
  options: { limit?: number; includeBlocked?: boolean } = {},
  signal?: AbortSignal,
): Promise<ToolTimelineResponse> {
  const query = { limit: options.limit, include_blocked: options.includeBlocked }
  return cached('getToolTimeline', [sessionId, query], (s) => request(`/observability/sessions/${seg(sessionId)}/tools`, { query, signal: s }), {
    signal,
    staleAfter: 'list',
  })
}

export interface TokenMetricsResponse {
  session_id: string
  total_input_tokens: number
  total_output_tokens: number
  total_tokens: number
  message_count: number
}

export function getTokenMetrics(sessionId: string, signal?: AbortSignal): Promise<TokenMetricsResponse> {
  return cached('getTokenMetrics', [sessionId], (s) => request(`/observability/sessions/${seg(sessionId)}/tokens`, { signal: s }), { signal, staleAfter: 'list' })
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

export function getConversationLog(
  sessionId: string,
  options: { offset?: number; limit?: number } = {},
  signal?: AbortSignal,
): Promise<ConversationLogResponse> {
  return cached('getConversationLog', [sessionId, options], (s) => request(`/conversations/${seg(sessionId)}`, { query: { ...options }, signal: s }), { signal, staleAfter: 'list' })
}

export interface SSEHealth {
  status: string
  active_executions: number
  active_connections: number
}

export function getSSEHealth(signal?: AbortSignal): Promise<SSEHealth> {
  return cached('getSSEHealth', [], (s) => request('/sse/health', { signal: s }), { signal, staleAfter: 'metrics' })
}

/** URL of one execution's event stream. */
export function executionStreamUrl(executionId: string): string {
  return `${clientConfig().baseUrl}/sse/executions/${seg(executionId)}`
}

/** URL of the global activity stream. */
export function activityStreamUrl(): string {
  return `${clientConfig().baseUrl}/sse/activity`
}

/** Which optional features this deployment has switched on. */
export type Features = components['schemas']['FeaturesResponse']

export function getFeatures(signal?: AbortSignal): Promise<Features> {
  return cached('getFeatures', [], (s) => request('/features', { signal: s }), { signal })
}

/** Which build of the API is answering, and when it went live. */
export type BuildInfo = components['schemas']['BuildInfo']

export function getBuildInfo(signal?: AbortSignal): Promise<BuildInfo> {
  return cached('getBuildInfo', [], (s) => request('/version', { signal: s }), { signal })
}
