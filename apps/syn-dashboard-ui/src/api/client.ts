import type {
  ArtifactResponse,
  ArtifactSummary,
  CostSummary,
  ExecutionCost,
  ExecutionDetailResponse,
  ExecutionHistoryResponse,
  ExecutionListResponse,
  MetricsResponse,
  SessionCost,
  SessionResponse,
  SessionSummary,
  WorkflowExecutionSummary,
  WorkflowListResponse,
  WorkflowResponse,
} from '../types'

export const API_BASE = '/api/v1'

// =============================================================================
// API CLIENT
// =============================================================================

async function fetchJSON<T>(url: string, options?: RequestInit): Promise<T> {
  const response = await fetch(url, {
    headers: {
      'Content-Type': 'application/json',
      ...options?.headers,
    },
    ...options,
  })

  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: response.statusText }))
    throw new Error(error.detail || `API Error: ${response.status}`)
  }

  return response.json()
}

// =============================================================================
// WORKFLOW API
// =============================================================================

export async function listWorkflows(params?: {
  workflow_type?: string
  page?: number
  page_size?: number
  order_by?: string
}): Promise<WorkflowListResponse> {
  const searchParams = new URLSearchParams()
  if (params?.workflow_type) searchParams.set('workflow_type', params.workflow_type)
  if (params?.page) searchParams.set('page', String(params.page))
  if (params?.page_size) searchParams.set('page_size', String(params.page_size))
  if (params?.order_by) searchParams.set('order_by', params.order_by)

  const query = searchParams.toString()
  return fetchJSON(`${API_BASE}/workflows${query ? `?${query}` : ''}`)
}

export async function getWorkflow(workflowId: string): Promise<WorkflowResponse> {
  return fetchJSON(`${API_BASE}/workflows/${workflowId}`)
}

export async function getWorkflowHistory(workflowId: string): Promise<ExecutionHistoryResponse> {
  return fetchJSON(`${API_BASE}/workflows/${workflowId}/history`)
}

export interface ExecuteWorkflowRequest {
  inputs?: Record<string, string>
  task?: string
  provider?: string
  max_budget_usd?: number
}

export interface ExecuteWorkflowResponse {
  execution_id: string
  workflow_id: string
  status: string
  message: string
}

export async function executeWorkflow(
  workflowId: string,
  request: ExecuteWorkflowRequest = {}
): Promise<ExecuteWorkflowResponse> {
  return fetchJSON(`${API_BASE}/workflows/${workflowId}/execute`, {
    method: 'POST',
    body: JSON.stringify(request),
  })
}

// =============================================================================
// EXECUTION API
// =============================================================================

export async function listExecutions(
  workflowId: string,
  params?: { page?: number; page_size?: number }
): Promise<WorkflowExecutionSummary[]> {
  const searchParams = new URLSearchParams()
  if (params?.page) searchParams.set('page', String(params.page))
  if (params?.page_size) searchParams.set('page_size', String(params.page_size))

  const query = searchParams.toString()
  const response = await fetchJSON<{ runs: WorkflowExecutionSummary[] }>(
    `${API_BASE}/workflows/${workflowId}/runs${query ? `?${query}` : ''}`
  )
  return response.runs ?? []
}

export async function getExecution(executionId: string): Promise<ExecutionDetailResponse> {
  return fetchJSON(`${API_BASE}/executions/${executionId}`)
}

export async function listAllExecutions(params?: {
  status?: string
  page?: number
  page_size?: number
}): Promise<ExecutionListResponse> {
  const searchParams = new URLSearchParams()
  if (params?.status) searchParams.set('status', params.status)
  if (params?.page) searchParams.set('page', String(params.page))
  if (params?.page_size) searchParams.set('page_size', String(params.page_size))

  const query = searchParams.toString()
  return fetchJSON(`${API_BASE}/executions${query ? `?${query}` : ''}`)
}

// =============================================================================
// SESSION API
// =============================================================================

export async function listSessions(params?: {
  workflow_id?: string
  status?: string
  limit?: number
}): Promise<SessionSummary[]> {
  const searchParams = new URLSearchParams()
  if (params?.workflow_id) searchParams.set('workflow_id', params.workflow_id)
  if (params?.status) searchParams.set('status', params.status)
  if (params?.limit) searchParams.set('limit', String(params.limit))

  const query = searchParams.toString()
  return fetchJSON(`${API_BASE}/sessions${query ? `?${query}` : ''}`)
}

export async function getSession(sessionId: string): Promise<SessionResponse> {
  return fetchJSON(`${API_BASE}/sessions/${sessionId}`)
}

// =============================================================================
// ARTIFACT API
// =============================================================================

export async function listArtifacts(params?: {
  workflow_id?: string
  phase_id?: string
  artifact_type?: string
  limit?: number
}): Promise<ArtifactSummary[]> {
  const searchParams = new URLSearchParams()
  if (params?.workflow_id) searchParams.set('workflow_id', params.workflow_id)
  if (params?.phase_id) searchParams.set('phase_id', params.phase_id)
  if (params?.artifact_type) searchParams.set('artifact_type', params.artifact_type)
  if (params?.limit) searchParams.set('limit', String(params.limit))

  const query = searchParams.toString()
  return fetchJSON(`${API_BASE}/artifacts${query ? `?${query}` : ''}`)
}

export async function getArtifact(
  artifactId: string,
  includeContent = false
): Promise<ArtifactResponse> {
  const query = includeContent ? '?include_content=true' : ''
  return fetchJSON(`${API_BASE}/artifacts/${artifactId}${query}`)
}

export async function getArtifactContent(
  artifactId: string
): Promise<{ artifact_id: string; content: string | null; content_type: string }> {
  return fetchJSON(`${API_BASE}/artifacts/${artifactId}/content`)
}

// =============================================================================
// METRICS API
// =============================================================================

export async function getMetrics(workflowId?: string): Promise<MetricsResponse> {
  const query = workflowId ? `?workflow_id=${workflowId}` : ''
  return fetchJSON(`${API_BASE}/metrics${query}`)
}

// =============================================================================
// OBSERVABILITY API
// =============================================================================

/**
 * Tool execution from ToolTimelineProjection (ADR-018 Pattern 2).
 * This is the preferred source for tool data over session.operations.
 */
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

/**
 * Get tool execution timeline for a session.
 * Uses the observability endpoint which pulls from ToolTimelineProjection.
 *
 * @param sessionId - The session ID
 * @param options - Optional parameters
 * @returns Tool timeline with execution details
 */
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

/**
 * Get token usage metrics for a session.
 * Uses the observability endpoint which pulls from TokenMetricsProjection.
 *
 * @param sessionId - The session ID
 * @returns Token metrics with aggregated data
 */
export async function getTokenMetrics(sessionId: string): Promise<TokenMetricsResponse> {
  return fetchJSON(`${API_BASE}/observability/sessions/${sessionId}/tokens`)
}

// =============================================================================
// SSE API
// =============================================================================

/**
 * Get the SSE URL for an execution event stream.
 *
 * Returns a relative URL — no protocol switching required; SSE runs over
 * plain HTTP/HTTPS just like every other API call.
 *
 *   Event Store → Subscription → ProjectionManager → RealTimeProjection → SSE
 *
 * @param executionId - The execution ID to subscribe to
 */
export function getExecutionSSEUrl(executionId: string): string {
  return `${API_BASE}/sse/executions/${executionId}`
}


export async function pauseExecution(
  executionId: string,
  reason?: string
): Promise<{ success: boolean; execution_id: string; state: string; message: string | null }> {
  return fetchJSON(`${API_BASE}/executions/${executionId}/pause`, {
    method: 'POST',
    body: JSON.stringify({ reason }),
  })
}

export async function resumeExecution(
  executionId: string
): Promise<{ success: boolean; execution_id: string; state: string; message: string | null }> {
  return fetchJSON(`${API_BASE}/executions/${executionId}/resume`, {
    method: 'POST',
  })
}

export async function cancelExecution(
  executionId: string,
  reason?: string
): Promise<{ success: boolean; execution_id: string; state: string; message: string | null }> {
  return fetchJSON(`${API_BASE}/executions/${executionId}/cancel`, {
    method: 'POST',
    body: JSON.stringify({ reason: reason ?? 'Cancelled from UI' }),
  })
}

/**
 * Check SSE subsystem health.
 */
export async function getSSEHealth(): Promise<{
  status: string
  active_executions: number
  active_connections: number
}> {
  return fetchJSON(`${API_BASE}/sse/health`)
}

// =============================================================================
// COST TRACKING API
// =============================================================================

/**
 * List session costs with optional filtering.
 */
export async function listSessionCosts(params?: {
  execution_id?: string
  limit?: number
}): Promise<SessionCost[]> {
  const searchParams = new URLSearchParams()
  if (params?.execution_id) searchParams.set('execution_id', params.execution_id)
  if (params?.limit) searchParams.set('limit', String(params.limit))

  const query = searchParams.toString()
  return fetchJSON(`${API_BASE}/costs/sessions${query ? `?${query}` : ''}`)
}

/**
 * Get cost for a specific session.
 */
export async function getSessionCost(
  sessionId: string,
  options?: { include_breakdown?: boolean }
): Promise<SessionCost> {
  const searchParams = new URLSearchParams()
  if (options?.include_breakdown !== undefined) {
    searchParams.set('include_breakdown', String(options.include_breakdown))
  }

  const query = searchParams.toString()
  return fetchJSON(`${API_BASE}/costs/sessions/${sessionId}${query ? `?${query}` : ''}`)
}

/**
 * List execution costs.
 */
export async function listExecutionCosts(params?: {
  limit?: number
}): Promise<ExecutionCost[]> {
  const searchParams = new URLSearchParams()
  if (params?.limit) searchParams.set('limit', String(params.limit))

  const query = searchParams.toString()
  return fetchJSON(`${API_BASE}/costs/executions${query ? `?${query}` : ''}`)
}

/**
 * Get aggregated cost for a workflow execution.
 */
export async function getExecutionCost(
  executionId: string,
  options?: { include_breakdown?: boolean; include_session_ids?: boolean }
): Promise<ExecutionCost> {
  const searchParams = new URLSearchParams()
  if (options?.include_breakdown !== undefined) {
    searchParams.set('include_breakdown', String(options.include_breakdown))
  }
  if (options?.include_session_ids !== undefined) {
    searchParams.set('include_session_ids', String(options.include_session_ids))
  }

  const query = searchParams.toString()
  return fetchJSON(`${API_BASE}/costs/executions/${executionId}${query ? `?${query}` : ''}`)
}

/**
 * Get summary of all costs across sessions and executions.
 */
export async function getCostSummary(): Promise<CostSummary> {
  return fetchJSON(`${API_BASE}/costs/summary`)
}

// =============================================================================
// CONVERSATION LOG API (ADR-035)
// =============================================================================

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

/**
 * Get conversation log for a session.
 *
 * @param sessionId - The session ID
 * @param options - Pagination options
 * @returns Conversation log with parsed lines
 */
// =============================================================================
// TRIGGER API
// =============================================================================

export interface TriggerSummary {
  trigger_id: string
  name: string
  event: string
  repository: string
  workflow_id: string
  status: string
  fire_count: number
}

export interface TriggerDetail extends TriggerSummary {
  conditions: Record<string, unknown> | null
  installation_id: string
  input_mapping: Record<string, unknown> | null
  config: Record<string, unknown> | null
  created_by: string
}

export interface TriggerHistoryEntry {
  fired_at: string | null
  execution_id: string | null
  webhook_delivery_id?: string | null
  event_type: string | null
  pr_number: number | null
  status: string | null
  cost_usd?: number | null
  trigger_id?: string
}

export async function listTriggers(params?: {
  repository?: string
  status?: string
}): Promise<{ triggers: TriggerSummary[]; total: number }> {
  const searchParams = new URLSearchParams()
  if (params?.repository) searchParams.set('repository', params.repository)
  if (params?.status) searchParams.set('status', params.status)

  const query = searchParams.toString()
  return fetchJSON(`${API_BASE}/triggers${query ? `?${query}` : ''}`)
}

export async function getTrigger(triggerId: string): Promise<TriggerDetail> {
  return fetchJSON(`${API_BASE}/triggers/${triggerId}`)
}

export async function deleteTrigger(triggerId: string): Promise<{ trigger_id: string; status: string }> {
  return fetchJSON(`${API_BASE}/triggers/${triggerId}`, { method: 'DELETE' })
}

export async function updateTrigger(
  triggerId: string,
  action: 'pause' | 'resume',
  reason?: string
): Promise<{ trigger_id: string; status: string; action: string }> {
  return fetchJSON(`${API_BASE}/triggers/${triggerId}`, {
    method: 'PATCH',
    body: JSON.stringify({ action, reason }),
  })
}

export async function getTriggerHistory(
  triggerId: string,
  limit = 50
): Promise<{ trigger_id: string; entries: TriggerHistoryEntry[] }> {
  return fetchJSON(`${API_BASE}/triggers/${triggerId}/history?limit=${limit}`)
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
