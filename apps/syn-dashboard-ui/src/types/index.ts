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

export interface InputDeclaration {
  name: string
  description: string | null
  required: boolean
  default: string | null
}

export interface PhaseDefinition {
  phase_id: string
  name: string
  order: number
  description: string | null
  agent_type: string
  prompt_template: string | null
  timeout_seconds: number
  allowed_tools: string[]
  argument_hint: string | null
  model: string | null
}

export interface WorkflowResponse {
  id: string
  name: string
  description: string | null
  workflow_type: string
  classification: string
  phases: PhaseDefinition[]
  input_declarations: InputDeclaration[]
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

export interface SubagentRecord {
  subagent_tool_use_id: string
  agent_name: string
  started_at: string | null
  stopped_at: string | null
  duration_ms: number | null
  tools_used: Record<string, number>
  success: boolean
}

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
  // Subagent metrics (from agentic_isolation v0.3.0)
  subagent_count?: number
  subagents?: SubagentRecord[]
  tools_by_subagent?: Record<string, Record<string, number>>
  num_turns?: number
  duration_api_ms?: number | null
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

  // Git details (for git_commit, git_push, git_branch_changed, git_operation)
  git_sha: string | null
  git_message: string | null
  git_branch: string | null
  git_repo: string | null
}

export interface SessionResponse {
  id: string
  workflow_id: string | null
  workflow_name: string | null
  execution_id: string | null
  phase_id: string | null
  milestone_id: string | null
  agent_provider: string | null
  agent_model: string | null
  status: string
  input_tokens: number
  output_tokens: number
  cache_creation_tokens: number
  cache_read_tokens: number
  total_tokens: number
  total_cost_usd: number
  cost_by_model: Record<string, string>
  operations: OperationInfo[]
  started_at: string | null
  completed_at: string | null
  duration_seconds: number | null
  error_message: string | null
  metadata: Record<string, unknown>
  // Subagent metrics (from agentic_isolation v0.3.0)
  subagent_count?: number
  subagents?: SubagentRecord[]
  tools_by_subagent?: Record<string, Record<string, number>>
  num_turns?: number
  duration_api_ms?: number | null
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
  /** Explicit naming for OTel correlation (ADR-028) */
  workflow_execution_id: string
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
  /** Explicit naming for OTel correlation (ADR-028) */
  workflow_execution_id: string
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
  /** Explicit naming for OTel correlation (ADR-028) */
  workflow_execution_id: string
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
  /** Explicit naming for OTel correlation (ADR-028) */
  workflow_phase_id: string
  name: string
  status: string
  session_id: string | null
  /** Claude CLI agent session ID for OTel correlation (ADR-028) */
  agent_session_id: string | null
  artifact_id: string | null
  input_tokens: number
  output_tokens: number
  cache_creation_tokens: number
  cache_read_tokens: number
  duration_seconds: number
  cost_usd: number
  started_at: string | null
  completed_at: string | null
  model: string | null
  cost_by_model: Record<string, string>
}

export interface ExecutionDetailResponse {
  /** Explicit naming for OTel correlation (ADR-028) */
  workflow_execution_id: string
  workflow_id: string
  workflow_name: string
  status: string
  started_at: string | null
  completed_at: string | null
  phases: PhaseExecutionDetail[]
  total_input_tokens: number
  total_output_tokens: number
  cache_creation_tokens: number
  cache_read_tokens: number
  total_tokens: number
  total_cost_usd: number
  artifact_ids: string[]
  error_message: string | null
  // Workspace info (ADR-021)
  workspace: WorkspaceInfo | null
}

// =============================================================================
// EVENT TYPES
// =============================================================================

/**
 * SSE event type constants used by UI components.
 *
 * NOTE: These are bridged from domain events defined in syn-domain.
 * The domain layer (Python) is the source of truth for event definitions.
 * Only add constants here for events the UI explicitly handles.
 */
export const SSE_EVENTS = {
  // Events that trigger execution refresh
  PHASE_STARTED: 'phase_started',
  PHASE_COMPLETED: 'phase_completed',
  WORKFLOW_COMPLETED: 'workflow_completed',
  WORKFLOW_FAILED: 'workflow_failed',

  // Live streaming (control plane)
  TURN_UPDATE: 'turn_update',

  // Subagent lifecycle events (agentic_isolation v0.3.0)
  SUBAGENT_STARTED: 'subagent_started',
  SUBAGENT_STOPPED: 'subagent_stopped',

  // Workspace lifecycle events (ADR-021)
  WORKSPACE_CREATING: 'workspace_creating',
  WORKSPACE_CREATED: 'workspace_created',
  WORKSPACE_COMMAND_EXECUTED: 'workspace_command_executed',
  WORKSPACE_DESTROYING: 'workspace_destroying',
  WORKSPACE_DESTROYED: 'workspace_destroyed',
  WORKSPACE_ERROR: 'workspace_error',

  // Git observability events (agentic-primitives observability plugin)
  GIT_COMMIT: 'git_commit',
  GIT_PUSH: 'git_push',
  GIT_BRANCH_CHANGED: 'git_branch_changed',
  GIT_OPERATION: 'git_operation',
  GIT_MERGE: 'git_merge',
  GIT_REWRITE: 'git_rewrite',
  GIT_CHECKOUT: 'git_checkout',
} as const

export type SSEEventType = typeof SSE_EVENTS[keyof typeof SSE_EVENTS]

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

  // Subagent event properties (for subagent_started, subagent_stopped)
  agent_name?: string
  subagent_tool_use_id?: string
  tools_used?: Record<string, number>
}

// =============================================================================
// WORKSPACE TYPES (ADR-021: Isolated Workspace Architecture)
// =============================================================================

export type IsolationBackend =
  | 'docker_hardened'
  | 'gvisor'
  | 'firecracker'
  | 'kata'
  | 'cloud'
  | 'local'

export interface WorkspaceInfo {
  workspace_id: string
  isolation_backend: IsolationBackend
  container_id: string | null
  vm_id: string | null
  sandbox_id: string | null
  workspace_path: string
  created_at: string
  started_at: string | null
  terminated_at: string | null
  memory_used_bytes: number
  cpu_time_seconds: number
  commands_executed: number
  status: 'creating' | 'running' | 'stopped' | 'error'
}

// =============================================================================
// STATUS HELPERS
// =============================================================================

export type WorkflowStatus = 'pending' | 'in_progress' | 'completed' | 'failed' | 'cancelled'
export type SessionStatus = 'pending' | 'running' | 'completed' | 'failed' | 'cancelled'
export type PhaseStatus = 'pending' | 'running' | 'completed' | 'failed' | 'skipped'

// =============================================================================
// COST TRACKING TYPES
// =============================================================================

export interface SessionCost {
  session_id: string
  execution_id: string | null
  workflow_id: string | null
  phase_id: string | null
  workspace_id: string | null

  // Cost totals
  total_cost_usd: number
  token_cost_usd: number
  compute_cost_usd: number

  // Token counts
  input_tokens: number
  output_tokens: number
  total_tokens: number
  cache_creation_tokens: number
  cache_read_tokens: number

  // Metrics
  tool_calls: number
  turns: number
  duration_ms: number

  // Breakdowns
  cost_by_model: Record<string, string>
  cost_by_tool: Record<string, string>

  // Tool token attribution (estimated)
  tokens_by_tool: Record<string, number>
  cost_by_tool_tokens: Record<string, string>

  // Status
  is_finalized: boolean
  started_at: string | null
  completed_at: string | null
}

export interface ExecutionCost {
  execution_id: string
  workflow_id: string | null

  // Session tracking
  session_count: number
  session_ids: string[]

  // Cost totals
  total_cost_usd: number
  token_cost_usd: number
  compute_cost_usd: number

  // Token counts
  input_tokens: number
  output_tokens: number
  total_tokens: number
  cache_creation_tokens: number
  cache_read_tokens: number

  // Metrics
  tool_calls: number
  turns: number
  duration_ms: number

  // Breakdowns
  cost_by_phase: Record<string, string>
  cost_by_model: Record<string, string>
  cost_by_tool: Record<string, string>

  // Status
  is_complete: boolean
  started_at: string | null
  completed_at: string | null
}

export interface CostSummary {
  total_cost_usd: number
  total_sessions: number
  total_executions: number
  total_tokens: number
  total_tool_calls: number
  top_models: Array<{ model: string; cost_usd: string }>
  top_sessions: Array<{ session_id: string; cost_usd: string; tokens: number }>
}
