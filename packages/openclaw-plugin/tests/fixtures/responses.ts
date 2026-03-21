/**
 * Typed mock API responses for testing.
 *
 * Each fixture matches the exact shape returned by syn-api endpoints.
 */

import type {
  ArtifactDetail,
  ArtifactSummary,
  ControlResponse,
  ExecutionCost,
  ExecutionDetail,
  ExecutionListResponse,
  ExecuteWorkflowResponse,
  MetricsResponse,
  SessionDetail,
  TriggerCreateResponse,
  TriggerListResponse,
  WorkflowListResponse,
} from "../../src/types.js";

export const workflowList: WorkflowListResponse = {
  workflows: [
    {
      id: "wf-issue-001",
      name: "Issue Resolution",
      workflow_type: "issue",
      phase_count: 3,
      created_at: "2026-03-15T10:00:00Z",
      runs_count: 12,
    },
    {
      id: "wf-review-001",
      name: "Code Review",
      workflow_type: "review",
      phase_count: 2,
      created_at: "2026-03-14T08:00:00Z",
      runs_count: 5,
    },
  ],
  total: 2,
  page: 1,
  page_size: 20,
};

export const executeResponse: ExecuteWorkflowResponse = {
  execution_id: "exec-abc-123",
  workflow_id: "wf-issue-001",
  status: "started",
  message: "Workflow execution started with provider 'claude'",
};

export const executionList: ExecutionListResponse = {
  executions: [
    {
      workflow_execution_id: "exec-abc-123",
      workflow_id: "wf-issue-001",
      workflow_name: "Issue Resolution",
      status: "running",
      started_at: "2026-03-16T12:00:00Z",
      completed_at: null,
      completed_phases: 1,
      total_phases: 3,
      total_tokens: 15000,
      total_cost_usd: "0.45",
      tool_call_count: 8,
    },
  ],
  total: 1,
  page: 1,
  page_size: 50,
};

export const executionDetail: ExecutionDetail = {
  workflow_execution_id: "exec-abc-123",
  workflow_id: "wf-issue-001",
  workflow_name: "Issue Resolution",
  status: "completed",
  started_at: "2026-03-16T12:00:00Z",
  completed_at: "2026-03-16T12:05:30Z",
  phases: [
    {
      phase_id: "phase-analyze",
      name: "Analyze",
      status: "completed",
      session_id: "sess-001",
      artifact_id: "art-001",
      input_tokens: 5000,
      output_tokens: 3000,
      total_tokens: 8000,
      duration_seconds: 120.5,
      cost_usd: "0.24",
      started_at: "2026-03-16T12:00:00Z",
      completed_at: "2026-03-16T12:02:00Z",
      error_message: null,
      operations: [],
    },
    {
      phase_id: "phase-implement",
      name: "Implement",
      status: "completed",
      session_id: "sess-002",
      artifact_id: "art-002",
      input_tokens: 10000,
      output_tokens: 7000,
      total_tokens: 17000,
      duration_seconds: 210.0,
      cost_usd: "0.51",
      started_at: "2026-03-16T12:02:00Z",
      completed_at: "2026-03-16T12:05:30Z",
      error_message: null,
      operations: [],
    },
  ],
  total_input_tokens: 15000,
  total_output_tokens: 10000,
  total_tokens: 25000,
  total_cost_usd: "0.75",
  total_duration_seconds: 330.5,
  artifact_ids: ["art-001", "art-002"],
  error_message: null,
};

export const controlPause: ControlResponse = {
  success: true,
  execution_id: "exec-abc-123",
  state: "paused",
  message: "Execution paused",
  error: null,
};

export const controlResume: ControlResponse = {
  success: true,
  execution_id: "exec-abc-123",
  state: "running",
  message: "Execution resumed",
  error: null,
};

export const controlCancel: ControlResponse = {
  success: true,
  execution_id: "exec-abc-123",
  state: "cancelled",
  message: "Execution cancelled",
  error: null,
};

export const controlInject: ControlResponse = {
  success: true,
  execution_id: "exec-abc-123",
  state: "running",
  message: null,
  error: null,
};

export const sessionDetail: SessionDetail = {
  id: "sess-001",
  workflow_id: "wf-issue-001",
  workflow_name: "Issue Resolution",
  execution_id: "exec-abc-123",
  phase_id: "phase-analyze",
  milestone_id: null,
  agent_provider: "claude",
  agent_model: "claude-sonnet-4-6",
  status: "completed",
  workspace_path: "/workspaces/exec-abc-123",
  input_tokens: 5000,
  output_tokens: 3000,
  total_tokens: 8000,
  total_cost_usd: "0.24",
  operations: [
    {
      operation_id: "op-001",
      operation_type: "tool_use",
      timestamp: "2026-03-16T12:00:30Z",
      duration_seconds: 2.5,
      success: true,
      input_tokens: null,
      output_tokens: null,
      total_tokens: null,
      tool_name: "Read",
      tool_use_id: "tu-001",
      tool_input: null,
      tool_output: null,
      message_role: null,
      message_content: null,
      git_sha: null,
      git_message: null,
      git_branch: null,
      git_repo: null,
    },
    {
      operation_id: "op-002",
      operation_type: "git_commit",
      timestamp: "2026-03-16T12:01:00Z",
      duration_seconds: null,
      success: true,
      input_tokens: null,
      output_tokens: null,
      total_tokens: null,
      tool_name: null,
      tool_use_id: null,
      tool_input: null,
      tool_output: null,
      message_role: null,
      message_content: null,
      git_sha: "abc1234",
      git_message: "fix: resolve null check",
      git_branch: "fix/issue-42",
      git_repo: "org/repo",
    },
  ],
  started_at: "2026-03-16T12:00:00Z",
  completed_at: "2026-03-16T12:02:00Z",
  duration_seconds: 120.0,
  error_message: null,
  metadata: {},
};

export const executionCost: ExecutionCost = {
  execution_id: "exec-abc-123",
  workflow_id: "wf-issue-001",
  session_count: 2,
  session_ids: ["sess-001", "sess-002"],
  total_cost_usd: "0.75",
  token_cost_usd: "0.70",
  compute_cost_usd: "0.05",
  input_tokens: 15000,
  output_tokens: 10000,
  total_tokens: 25000,
  cache_creation_tokens: 2000,
  cache_read_tokens: 5000,
  tool_calls: 12,
  turns: 6,
  duration_ms: 330500,
  cost_by_phase: { "phase-analyze": "0.24", "phase-implement": "0.51" },
  cost_by_model: { "claude-sonnet-4-6": "0.75" },
  cost_by_tool: { Read: "0.10", Edit: "0.15" },
  is_complete: true,
  started_at: "2026-03-16T12:00:00Z",
  completed_at: "2026-03-16T12:05:30Z",
};

export const metricsResponse: MetricsResponse = {
  total_workflows: 5,
  completed_workflows: 3,
  failed_workflows: 1,
  total_sessions: 20,
  total_input_tokens: 100000,
  total_output_tokens: 75000,
  total_tokens: 175000,
  total_cost_usd: "5.25",
  total_artifacts: 15,
  total_artifact_bytes: 102400,
  phases: [],
};

export const artifactList: ArtifactSummary[] = [
  {
    id: "art-001",
    workflow_id: "wf-issue-001",
    phase_id: "phase-analyze",
    artifact_type: "analysis",
    title: "Issue Analysis Report",
    size_bytes: 4096,
    created_at: "2026-03-16T12:02:00Z",
  },
];

export const artifactDetail: ArtifactDetail = {
  id: "art-001",
  workflow_id: "wf-issue-001",
  phase_id: "phase-analyze",
  session_id: "sess-001",
  artifact_type: "analysis",
  is_primary_deliverable: true,
  content: "# Issue Analysis\n\nThe issue is caused by a null check missing in `handler.ts`.",
  content_type: "text/markdown",
  content_hash: "sha256:abc123",
  size_bytes: 4096,
  title: "Issue Analysis Report",
  derived_from: [],
  created_at: "2026-03-16T12:02:00Z",
  created_by: "claude",
  metadata: {},
};

export const triggerList: TriggerListResponse = {
  triggers: [
    {
      trigger_id: "trig-001",
      name: "Auto-resolve issues",
      event: "issues.opened",
      repository: "org/repo",
      workflow_id: "wf-issue-001",
      status: "active",
      fire_count: 7,
    },
  ],
  total: 1,
};

export const triggerCreated: TriggerCreateResponse = {
  trigger_id: "trig-002",
  name: "PR Review Trigger",
  status: "active",
};
