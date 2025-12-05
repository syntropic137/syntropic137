import type {
  ArtifactResponse,
  ArtifactSummary,
  EventMessage,
  ExecutionDetailResponse,
  ExecutionHistoryResponse,
  ExecutionListResponse,
  MetricsResponse,
  SessionResponse,
  SessionSummary,
  WorkflowExecutionSummary,
  WorkflowListResponse,
  WorkflowResponse,
} from '../types'

const API_BASE = '/api'

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
}): Promise<WorkflowListResponse> {
  const searchParams = new URLSearchParams()
  if (params?.workflow_type) searchParams.set('workflow_type', params.workflow_type)
  if (params?.page) searchParams.set('page', String(params.page))
  if (params?.page_size) searchParams.set('page_size', String(params.page_size))

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
// EVENTS API
// =============================================================================

export async function getRecentEvents(): Promise<EventMessage[]> {
  return fetchJSON(`${API_BASE}/events/recent`)
}

export function subscribeToEvents(
  onEvent: (event: EventMessage) => void,
  onError?: (error: Event) => void,
  onConnected?: () => void
): () => void {
  const eventSource = new EventSource(`${API_BASE}/events/stream`)

  // Handle named 'connected' event
  eventSource.addEventListener('connected', () => {
    console.log('SSE connected to server')
    onConnected?.()
  })

  // Handle named 'heartbeat' event - keeps connection status alive
  eventSource.addEventListener('heartbeat', () => {
    onConnected?.()
  })

  // Handle all other named events (workflow_started, phase_completed, etc.)
  const eventTypes = [
    'workflow_started',
    'workflow_completed',
    'workflow_failed',
    'phase_started',
    'phase_completed',
    'phase_failed',
    'session_started',
    'session_completed',
    'session_failed',
  ]

  eventTypes.forEach((eventType) => {
    eventSource.addEventListener(eventType, (event: MessageEvent) => {
      try {
        const data = JSON.parse(event.data)
        onEvent({
          event_type: eventType,
          timestamp: data.timestamp || new Date().toISOString(),
          ...data,
        } as EventMessage)
      } catch (e) {
        console.error('Failed to parse event:', e)
      }
    })
  })

  // Handle unnamed events (fallback)
  eventSource.onmessage = (event) => {
    try {
      const data = JSON.parse(event.data) as EventMessage
      onEvent(data)
    } catch (e) {
      console.error('Failed to parse event:', e)
    }
  }

  eventSource.onerror = (error) => {
    console.error('SSE connection error:', error)
    onError?.(error)
  }

  // Return cleanup function
  return () => {
    eventSource.close()
  }
}
