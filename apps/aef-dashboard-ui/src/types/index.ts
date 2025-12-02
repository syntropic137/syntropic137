// =============================================================================
// WORKFLOW TYPES
// =============================================================================

export interface WorkflowSummary {
  id: string
  name: string
  workflow_type: string
  status: string
  phase_count: number
  created_at: string | null
}

export interface PhaseInfo {
  phase_id: string
  name: string
  order: number
  description: string | null
  status: string
  artifact_id: string | null
}

export interface WorkflowResponse {
  id: string
  name: string
  description: string | null
  workflow_type: string
  classification: string
  status: string
  phases: PhaseInfo[]
  created_at: string | null
  updated_at: string | null
  metadata: Record<string, unknown>
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
  input_tokens: number | null
  output_tokens: number | null
  total_tokens: number | null
  tool_name: string | null
  success: boolean
}

export interface SessionResponse {
  id: string
  workflow_id: string | null
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
// EVENT TYPES
// =============================================================================

export interface EventMessage {
  event_type: string
  timestamp: string
  workflow_id: string | null
  phase_id: string | null
  session_id: string | null
  data: Record<string, unknown>
}

// =============================================================================
// STATUS HELPERS
// =============================================================================

export type WorkflowStatus = 'pending' | 'in_progress' | 'completed' | 'failed' | 'cancelled'
export type SessionStatus = 'pending' | 'running' | 'completed' | 'failed' | 'cancelled'
export type PhaseStatus = 'pending' | 'running' | 'completed' | 'failed' | 'skipped'

