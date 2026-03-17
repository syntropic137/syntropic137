/**
 * Response types mirroring syn-api Pydantic models.
 *
 * Field names match the JSON wire format (snake_case).
 * Optional fields use `T | null` to match Python's `None`.
 */

// ---------------------------------------------------------------------------
// Workflows
// ---------------------------------------------------------------------------

export interface WorkflowSummary {
  id: string;
  name: string;
  workflow_type: string;
  phase_count: number;
  created_at: string | null;
  runs_count: number;
}

export interface PhaseDefinition {
  phase_id: string;
  name: string;
  order: number;
  description: string | null;
  agent_type: string;
  prompt_template: string | null;
  timeout_seconds: number;
  allowed_tools: string[];
}

export interface WorkflowDetail {
  id: string;
  name: string;
  description: string | null;
  workflow_type: string;
  classification: string;
  phases: PhaseDefinition[];
  created_at: string | null;
  runs_count: number;
  runs_link: string | null;
}

export interface WorkflowListResponse {
  workflows: WorkflowSummary[];
  total: number;
  page: number;
  page_size: number;
}

// ---------------------------------------------------------------------------
// Execution
// ---------------------------------------------------------------------------

export interface ExecuteWorkflowRequest {
  inputs?: Record<string, string>;
  provider?: string;
  max_budget_usd?: number | null;
}

export interface ExecuteWorkflowResponse {
  execution_id: string;
  workflow_id: string;
  status: string;
  message: string;
}

export interface PhaseOperationInfo {
  operation_id: string;
  operation_type: string;
  timestamp: string | null;
  tool_name: string | null;
  tool_use_id: string | null;
  success: boolean;
}

export interface PhaseExecutionInfo {
  phase_id: string;
  name: string;
  status: string;
  session_id: string | null;
  artifact_id: string | null;
  input_tokens: number;
  output_tokens: number;
  total_tokens: number;
  duration_seconds: number;
  cost_usd: string;
  started_at: string | null;
  completed_at: string | null;
  error_message: string | null;
  operations: PhaseOperationInfo[];
}

export interface ExecutionDetail {
  workflow_execution_id: string;
  workflow_id: string;
  workflow_name: string;
  status: string;
  started_at: string | null;
  completed_at: string | null;
  phases: PhaseExecutionInfo[];
  total_input_tokens: number;
  total_output_tokens: number;
  total_tokens: number;
  total_cost_usd: string;
  total_duration_seconds: number;
  artifact_ids: string[];
  error_message: string | null;
}

export interface ExecutionSummary {
  workflow_execution_id: string;
  workflow_id: string;
  workflow_name: string;
  status: string;
  started_at: string | null;
  completed_at: string | null;
  completed_phases: number;
  total_phases: number;
  total_tokens: number;
  total_cost_usd: string;
  tool_call_count: number;
}

export interface ExecutionListResponse {
  executions: ExecutionSummary[];
  total: number;
  page: number;
  page_size: number;
}

// ---------------------------------------------------------------------------
// Control
// ---------------------------------------------------------------------------

export interface ControlResponse {
  success: boolean;
  execution_id: string;
  state: string;
  message: string | null;
  error: string | null;
}

// ---------------------------------------------------------------------------
// Sessions
// ---------------------------------------------------------------------------

export interface OperationInfo {
  operation_id: string;
  operation_type: string;
  timestamp: string | null;
  duration_seconds: number | null;
  success: boolean;
  input_tokens: number | null;
  output_tokens: number | null;
  total_tokens: number | null;
  tool_name: string | null;
  tool_use_id: string | null;
  tool_input: Record<string, unknown> | null;
  tool_output: string | null;
  message_role: string | null;
  message_content: string | null;
  git_sha: string | null;
  git_message: string | null;
  git_branch: string | null;
  git_repo: string | null;
}

export interface SessionDetail {
  id: string;
  workflow_id: string | null;
  workflow_name: string | null;
  execution_id: string | null;
  phase_id: string | null;
  milestone_id: string | null;
  agent_provider: string | null;
  agent_model: string | null;
  status: string;
  workspace_path: string | null;
  input_tokens: number;
  output_tokens: number;
  total_tokens: number;
  total_cost_usd: string;
  operations: OperationInfo[];
  started_at: string | null;
  completed_at: string | null;
  duration_seconds: number | null;
  error_message: string | null;
  metadata: Record<string, unknown>;
}

// ---------------------------------------------------------------------------
// Costs
// ---------------------------------------------------------------------------

export interface ExecutionCost {
  execution_id: string;
  workflow_id: string | null;
  session_count: number;
  session_ids: string[];
  total_cost_usd: string;
  token_cost_usd: string;
  compute_cost_usd: string;
  input_tokens: number;
  output_tokens: number;
  total_tokens: number;
  cache_creation_tokens: number;
  cache_read_tokens: number;
  tool_calls: number;
  turns: number;
  duration_ms: number;
  cost_by_phase: Record<string, string>;
  cost_by_model: Record<string, string>;
  cost_by_tool: Record<string, string>;
  is_complete: boolean;
  started_at: string | null;
  completed_at: string | null;
}

// ---------------------------------------------------------------------------
// Metrics
// ---------------------------------------------------------------------------

export interface PhaseMetrics {
  phase_id: string;
  phase_name: string;
  status: string;
  input_tokens: number;
  output_tokens: number;
  total_tokens: number;
  cost_usd: string;
  duration_seconds: number;
  artifact_count: number;
}

export interface MetricsResponse {
  total_workflows: number;
  completed_workflows: number;
  failed_workflows: number;
  total_sessions: number;
  total_input_tokens: number;
  total_output_tokens: number;
  total_tokens: number;
  total_cost_usd: string;
  total_artifacts: number;
  total_artifact_bytes: number;
  phases: PhaseMetrics[];
}

// ---------------------------------------------------------------------------
// Artifacts
// ---------------------------------------------------------------------------

export interface ArtifactSummary {
  id: string;
  workflow_id: string | null;
  phase_id: string | null;
  artifact_type: string;
  title: string | null;
  size_bytes: number;
  created_at: string | null;
}

export interface ArtifactDetail {
  id: string;
  workflow_id: string | null;
  phase_id: string | null;
  session_id: string | null;
  artifact_type: string;
  is_primary_deliverable: boolean;
  content: string | null;
  content_type: string;
  content_hash: string | null;
  size_bytes: number;
  title: string | null;
  derived_from: string[];
  created_at: string | null;
  created_by: string | null;
  metadata: Record<string, unknown>;
}

// ---------------------------------------------------------------------------
// Triggers
// ---------------------------------------------------------------------------

export interface TriggerSummary {
  trigger_id: string;
  name: string;
  event: string;
  repository: string;
  workflow_id: string;
  status: string;
  fire_count: number;
}

export interface TriggerDetail {
  trigger_id: string;
  name: string;
  event: string;
  conditions: Record<string, unknown>;
  repository: string;
  installation_id: string | null;
  workflow_id: string;
  input_mapping: Record<string, string>;
  status: string;
  fire_count: number;
  config: Record<string, unknown>;
  created_by: string | null;
}

export interface TriggerListResponse {
  triggers: TriggerSummary[];
  total: number;
}

export interface TriggerCreateResponse {
  trigger_id: string;
  name: string;
  status: string;
}
