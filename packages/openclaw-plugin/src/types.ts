/**
 * The plugin's names for the syn-api response schemas.
 *
 * Every type here is an alias onto `src/generated/api-types.ts`, which
 * `just codegen` writes from the OpenAPI spec. Nothing in this file describes
 * a shape; it only records WHICH generated schema each tool is reading, and
 * that mapping is the one thing a generator cannot infer.
 *
 * These were hand-written interfaces until #1182. They were a structural
 * SUBSET of the server's responses -- fields the API added were simply absent
 * rather than wrong, so extra JSON keys stayed inert at runtime and no test
 * could see the gap. `/executions` had grown `status_counts` and
 * `excluded_undated`, and `ExecutionSummaryResponse` `total_tokens_display`,
 * before anyone noticed. Now a rename or a removal on the server is a
 * compile error here, and a spec change nobody regenerated fails
 * `just codegen-check`.
 *
 * One consequence worth knowing before you read the tools: a Pydantic field
 * with a `default_factory` is absent from the spec's `required` list, so every
 * list- and dict-valued field arrives here as `T[] | undefined`. The tools
 * therefore read them as `x ?? []`. That is not defensive padding -- it is the
 * contract the server publishes, and the hand-written types denied it.
 *
 * The API's own names carry a `Response` suffix that reads as noise at the
 * call site (`client.get<ArtifactResponse>` for one artifact), so the local
 * names stay. Adding a tool means adding one line here, not an interface.
 */

import type { components } from "./generated/api-types.js";

type Schemas = components["schemas"];

// ---------------------------------------------------------------------------
// Workflows
// ---------------------------------------------------------------------------

export type WorkflowSummary = Schemas["WorkflowSummaryResponse"];
export type PhaseDefinition = Schemas["PhaseDefinitionResponse"];
export type WorkflowDetail = Schemas["WorkflowResponse"];
export type WorkflowListResponse = Schemas["WorkflowListResponse"];

// ---------------------------------------------------------------------------
// Execution
// ---------------------------------------------------------------------------

export type ExecuteWorkflowRequest = Schemas["ExecuteWorkflowRequest"];
export type ExecuteWorkflowResponse = Schemas["ExecuteWorkflowResponse"];
export type PhaseOperationInfo = Schemas["PhaseOperationInfo"];
export type PhaseExecutionInfo = Schemas["PhaseExecutionInfo"];
export type ExecutionDetail = Schemas["ExecutionDetailResponse"];
export type ExecutionSummary = Schemas["ExecutionSummaryResponse"];
export type ExecutionListResponse = Schemas["ExecutionListResponse"];

// ---------------------------------------------------------------------------
// Control
// ---------------------------------------------------------------------------

export type ControlResponse = Schemas["ControlResponse"];

// ---------------------------------------------------------------------------
// Sessions
// ---------------------------------------------------------------------------

export type OperationInfo = Schemas["OperationInfo"];
export type SessionDetail = Schemas["SessionResponse"];

// ---------------------------------------------------------------------------
// Costs
// ---------------------------------------------------------------------------

export type ExecutionCost = Schemas["ExecutionCostResponse"];

// ---------------------------------------------------------------------------
// Metrics
// ---------------------------------------------------------------------------

export type PhaseMetrics = Schemas["PhaseMetrics"];
export type MetricsResponse = Schemas["MetricsResponse"];

// ---------------------------------------------------------------------------
// Artifacts
// ---------------------------------------------------------------------------

export type ArtifactSummary = Schemas["ArtifactSummaryResponse"];
export type ArtifactListResponse = Schemas["ArtifactListResponse"];
export type ArtifactDetail = Schemas["ArtifactResponse"];

// ---------------------------------------------------------------------------
// Triggers
// ---------------------------------------------------------------------------

export type TriggerSummary = Schemas["TriggerSummary"];
export type TriggerDetail = Schemas["TriggerDetail"];
export type TriggerListResponse = Schemas["TriggerListResponse"];
/** POST /triggers answers with the generic trigger-action envelope. */
export type TriggerCreateResponse = Schemas["TriggerActionResponse"];
