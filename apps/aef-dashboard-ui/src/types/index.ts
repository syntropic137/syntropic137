// =============================================================================
// WORKFLOW TEMPLATE TYPES
// Note: Templates don't have status. Status belongs to Executions.
// =============================================================================

export interface WorkflowSummary {
  id: string
  name: string
  workflow_type: string
  phase_count: number
  created_at: string | null
  runs_count: number
}

export interface PhaseDefinition {
  phase_id: string
  name: string
  order: number
  description: string | null
  agent_type: string
}

export interface WorkflowResponse {
  id: string
  name: string
  description: string | null
  workflow_type: string
  classification: string
  phases: PhaseDefinition[]
  created_at: string | null
  runs_count: number
  runs_link: string | null
}

export interface WorkflowListResponse {
  workflows: WorkflowSummary[]
  total: number
  page: number
  page_size: number
}

// =============================================================================
// SESSION TYPES
// =============================================================================

export interface SessionSummary {
  id: string
  workflow_id: string | null
  execution_id: string | null
  phase_id: string | null
  status: string
  agent_provider: string | null
  total_tokens: number
  total_cost_usd: number
  started_at: string | null
  completed_at: string | null
}

export interface OperationInfo {
  operation_id: string
  operation_type: string
  timestamp: string
  duration_seconds: number | null
  success: boolean

  // Token metrics (for MESSAGE_* types)
  input_tokens: number | null
  output_tokens: number | null
  total_tokens: number | null

  // Tool details (for TOOL_* types)
  tool_name: string | null
  tool_use_id: string | null
  tool_input: Record<string, unknown> | null
  tool_output: string | null

  // Message details (for MESSAGE_* types)
  message_role: string | null
  message_content: string | null

  // Thinking details (for THINKING type)
  thinking_content: string | null
}

export interface SessionResponse {
  id: string
  workflow_id: string | null
  execution_id: string | null
  phase_id: string | null
  milestone_id: string | null
  agent_provider: string | null
  agent_model: string | null
  status: string
  input_tokens: number
  output_tokens: number
  total_tokens: number
  total_cost_usd: number
  operations: OperationInfo[]
  started_at: string | null
  completed_at: string | null
  duration_seconds: number | null
  error_message: string | null
  metadata: Record<string, unknown>
}

// =============================================================================
// ARTIFACT TYPES
// =============================================================================

export interface ArtifactSummary {
  id: string
  workflow_id: string | null
  phase_id: string | null
  artifact_type: string
  title: string | null
  size_bytes: number
  created_at: string | null
}

export interface ArtifactResponse {
  id: string
  workflow_id: string | null
  phase_id: string | null
  session_id: string | null
  artifact_type: string
  is_primary_deliverable: boolean
  content: string | null
  content_type: string
  content_hash: string | null
  size_bytes: number
  title: string | null
  derived_from: string[]
  created_at: string | null
  created_by: string | null
  metadata: Record<string, unknown>
}

// =============================================================================
// METRICS TYPES
// =============================================================================

export interface PhaseMetrics {
  phase_id: string
  phase_name: string
  status: string
  input_tokens: number
  output_tokens: number
  total_tokens: number
  cost_usd: number
  duration_seconds: number
  artifact_count: number
}

export interface MetricsResponse {
  total_workflows: number
  completed_workflows: number
  failed_workflows: number
  total_sessions: number
  total_input_tokens: number
  total_output_tokens: number
  total_tokens: number
  total_cost_usd: number
  total_artifacts: number
  total_artifact_bytes: number
  phases: PhaseMetrics[]
}

// =============================================================================
// EXECUTION HISTORY TYPES
// =============================================================================

export interface ExecutionRun {
  execution_id: string
  status: string
  started_at: string | null
  completed_at: string | null
  total_tokens: number
  total_cost_usd: number
  phase_results: PhaseMetrics[]
  error_message: string | null
}

export interface ExecutionHistoryResponse {
  workflow_id: string
  workflow_name: string
  executions: ExecutionRun[]
  total_executions: number
}

// =============================================================================
// WORKFLOW EXECUTION TYPES (NEW)
// =============================================================================

export interface WorkflowExecutionSummary {
  execution_id: string
  workflow_id: string
  status: string
  started_at: string | null
  completed_at: string | null
  completed_phases: number
  total_phases: number
  total_tokens: number
  total_cost_usd: number
}

/** Item in the global execution list (includes workflow_name) */
export interface ExecutionListItem {
  execution_id: string
  workflow_id: string
  workflow_name: string
  status: string
  started_at: string | null
  completed_at: string | null
  completed_phases: number
  total_phases: number
  total_tokens: number
  total_cost_usd: number
  tool_call_count: number
}

export interface ExecutionListResponse {
  executions: ExecutionListItem[]
  total: number
  page: number
  page_size: number
}

export interface PhaseExecutionDetail {
  phase_id: string
  name: string
  status: string
  session_id: string | null
  artifact_id: string | null
  input_tokens: number
  output_tokens: number
  duration_seconds: number
  cost_usd: number
}

export interface ExecutionDetailResponse {
  execution_id: string
  workflow_id: string
  workflow_name: string
  status: string
  started_at: string | null
  completed_at: string | null
  phases: PhaseExecutionDetail[]
  total_input_tokens: number
  total_output_tokens: number
  total_cost_usd: number
  artifact_ids: string[]
  error_message: string | null
}

// =============================================================================
// EVENT TYPES
// =============================================================================

export interface EventMessage {
  event_type: string
  timestamp: string
  workflow_id: string | null
  execution_id: string | null
  phase_id: string | null
  session_id: string | null
  data: Record<string, unknown>

  // Tool event properties (for tool_execution_started, tool_execution_completed, tool_blocked)
  tool_name?: string
  tool_use_id?: string
  tool_input?: Record<string, unknown>
  duration_ms?: number
  success?: boolean
  reason?: string
}

// =============================================================================
// STATUS HELPERS
// =============================================================================

export type WorkflowStatus = 'pending' | 'in_progress' | 'completed' | 'failed' | 'cancelled'
export type SessionStatus = 'pending' | 'running' | 'completed' | 'failed' | 'cancelled'
export type PhaseStatus = 'pending' | 'running' | 'completed' | 'failed' | 'skipped'
