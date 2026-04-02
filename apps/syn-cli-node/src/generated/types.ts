/**
 * Convenience type aliases for generated OpenAPI schema types.
 * Import from here instead of navigating components["schemas"]["..."].
 *
 * @generated — regenerate api-types.ts with: pnpm generate:types
 */

import type { components } from "./api-types.js";

// --- Workflows ---
export type WorkflowSummaryResponse = components["schemas"]["WorkflowSummaryResponse"];
export type WorkflowResponse = components["schemas"]["WorkflowResponse"];
export type WorkflowListResponse = components["schemas"]["WorkflowListResponse"];
export type CreateWorkflowRequest = components["schemas"]["CreateWorkflowRequest"];
export type CreateWorkflowResponse = components["schemas"]["CreateWorkflowResponse"];
export type DeleteWorkflowResponse = components["schemas"]["DeleteWorkflowResponse"];
export type ValidateYamlRequest = components["schemas"]["ValidateYamlRequest"];
export type ValidateYamlResponse = components["schemas"]["ValidateYamlResponse"];
export type PhaseDefinition = components["schemas"]["PhaseDefinition"];
export type InputDeclarationModel = components["schemas"]["InputDeclarationModel"];

// --- Executions ---
export type ExecutionListResponse = components["schemas"]["ExecutionListResponse"];
export type ExecutionSummaryResponse = components["schemas"]["ExecutionSummaryResponse"];
export type ExecutionDetailResponse = components["schemas"]["ExecutionDetailResponse"];
export type ExecutionRunListResponse = components["schemas"]["ExecutionRunListResponse"];
export type ExecutionRunSummary = components["schemas"]["ExecutionRunSummary"];
export type ExecutionStatusResponse = components["schemas"]["ExecutionStatusResponse"];
export type ExecutionHistoryResponse = components["schemas"]["ExecutionHistoryResponse"];
export type ExecuteWorkflowRequest = components["schemas"]["ExecuteWorkflowRequest"];
export type ExecuteWorkflowResponse = components["schemas"]["ExecuteWorkflowResponse"];
export type PhaseExecutionInfo = components["schemas"]["PhaseExecutionInfo"];

// --- Sessions ---
export type SessionResponse = components["schemas"]["SessionResponse"];
export type SessionSummaryResponse = components["schemas"]["SessionSummaryResponse"];
export type OperationInfo = components["schemas"]["OperationInfo"];

// --- Costs ---
export type SessionCostResponse = components["schemas"]["SessionCostResponse"];
export type ExecutionCostResponse = components["schemas"]["ExecutionCostResponse"];
export type CostSummaryResponse = components["schemas"]["syn_api__routes__costs__CostSummaryResponse"];
export type EventsCostSummaryResponse = components["schemas"]["syn_api__routes__events__CostSummaryResponse"];

// --- Events ---
export type EventListResponse = components["schemas"]["EventListResponse"];
export type EventResponse = components["schemas"]["EventResponse"];
export type TimelineEntryResponse = components["schemas"]["TimelineEntryResponse"];
export type ToolSummary = components["schemas"]["ToolSummary"];

// --- Artifacts ---
export type ArtifactResponse = components["schemas"]["ArtifactResponse"];
export type ArtifactSummaryResponse = components["schemas"]["ArtifactSummaryResponse"];
export type ArtifactContentResponse = components["schemas"]["ArtifactContentResponse"];
export type CreateArtifactRequest = components["schemas"]["CreateArtifactRequest"];
export type CreateArtifactResponse = components["schemas"]["CreateArtifactResponse"];

// --- Conversations ---
export type ConversationLogResponse = components["schemas"]["ConversationLogResponse"];
export type ConversationLineResponse = components["schemas"]["ConversationLineResponse"];
export type ConversationMetadataResponse = components["schemas"]["ConversationMetadataResponse"];

// --- Control ---
export type ControlResponse = components["schemas"]["ControlResponse"];
export type StateResponse = components["schemas"]["StateResponse"];

// --- Metrics ---
export type MetricsResponse = components["schemas"]["MetricsResponse"];
export type PhaseMetrics = components["schemas"]["PhaseMetrics"];

// --- Validation ---
export type ValidationError = components["schemas"]["ValidationError"];
export type HTTPValidationError = components["schemas"]["HTTPValidationError"];
