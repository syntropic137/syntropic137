/**
 * Response types for the syn-api routes this plugin calls.
 *
 * Every type here is a name for a schema in `./generated/api-types.ts`, which
 * `just codegen` regenerates from the API's OpenAPI spec (#1182). Nothing is
 * hand-written: a field the API adds, renames or drops changes these types, and
 * `just codegen-check` fails until the regenerated file is committed. The local
 * names are kept so call sites read as the plugin's vocabulary, not the spec's.
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
/** What `POST /executions/{id}/resume` returns: the child run it created. */
export type ResumeResponse = Schemas["ResumeResponse"];

// ---------------------------------------------------------------------------
// Sessions, costs, metrics
// ---------------------------------------------------------------------------

export type OperationInfo = Schemas["OperationInfo"];
export type SessionDetail = Schemas["SessionResponse"];
export type ExecutionCost = Schemas["ExecutionCostResponse"];
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
export type TriggerCreateResponse = Schemas["TriggerActionResponse"];

// ---------------------------------------------------------------------------
// Session inventory (#1398)
// ---------------------------------------------------------------------------

export type CoverageState = Schemas["CoverageState"];
export type EvidenceClass = Schemas["EvidenceClass"];
export type BodyAvailability = Schemas["BodyAvailability"];
export type RunIdentity = Schemas["RunIdentity"];
export type InventoryNamespaceCount = Schemas["InventoryNamespaceCount"];
export type InventoryCounts = Schemas["InventoryCounts"];
export type InventoryCoverage = Schemas["InventoryCoverage"];
export type InventorySnapshot = Schemas["InventorySnapshot"];
export type SessionInventoryNamespace = Schemas["SessionInventoryNamespace"];
export type SessionInventorySummary = Schemas["SessionInventorySummary"];
export type SessionInventoryResponse = Schemas["SessionInventoryResponse"];
export type ReconstructionStatus = SessionInventoryResponse["reconstruction_status"];
export type EvidenceReference = Schemas["EvidenceReference"];
export type InventoryNodeRef = Schemas["InventoryNodeRef"];
export type NodeKind = InventoryNodeRef["kind"];
export type InventoryNode = Schemas["InventoryNode"];
export type Membership = Schemas["Membership"];
export type LineageEdge = Schemas["LineageEdge"];
export type CaptureReceipt = Schemas["CaptureReceipt"];
export type InventoryGap = Schemas["InventoryGap"];
export type EvidenceRetraction = Schemas["EvidenceRetraction"];
export type IdentityBinding = Schemas["IdentityBinding"];
export type InventoryFilter = Schemas["InventoryFilter"];
export type InventoryItemKeys = Schemas["InventoryItemKeys"];
export type TranscriptBodyState = Schemas["TranscriptBodyState"];
/** Which representation a capture receipt's hashes are. Never compare hashes of different kinds. */
export type CaptureRevisionHashes = Schemas["CaptureRevisionHashes"];
export type SessionInventoryPageResponse = Schemas["SessionInventoryPageResponse"];
export type InventoryKind = SessionInventoryPageResponse["kind"];
export type InventoryItem = SessionInventoryPageResponse["items"][number];
export type SessionInventoryNodeResponse = Schemas["SessionInventoryNodeResponse"];
export type SessionInventoryCursorError = Schemas["SessionInventoryCursorError"];

/** Field lists for drift checks: `satisfies` makes each list exactly the interface's keys. */
type Keys<T> = { [K in keyof Required<T>]: true };
export const inventoryFieldKeys = {
  SessionInventoryResponse: { run: true, snapshot: true, reconstruction_status: true, observed_evidence_watermark: true, later_evidence_pending: true, job_id: true, summary: true } satisfies Keys<SessionInventoryResponse>,
  SessionInventorySummary: { complete: true, coverage_state: true, coverage_display: true, revision: true, distinct_sessions: true, platform_sessions: true, invocations: true, native_transcripts: true, gaps: true, namespaces: true, counts_display: true, remote_replication: true, follow_up_command: true } satisfies Keys<SessionInventorySummary>,
  SessionInventoryNamespace: { namespace: true, kind: true, harness: true, count: true } satisfies Keys<SessionInventoryNamespace>,
  InventorySnapshot: { snapshot_id: true, run: true, revision: true, resolver_version: true, evidence_watermark: true, coverage: true, counts: true } satisfies Keys<InventorySnapshot>,
  InventoryCounts: { node: true, membership: true, edge: true, capture: true, gap: true, retraction: true, binding: true, namespaces: true } satisfies Keys<InventoryCounts>,
  InventoryCoverage: { state: true, contract_id: true, expected_count: true, missing_keys: true } satisfies Keys<InventoryCoverage>,
  SessionInventoryPageResponse: { snapshot: true, kind: true, filters: true, items: true, item_keys: true, next_cursor: true, body_overrides: true, capture_hashes: true } satisfies Keys<SessionInventoryPageResponse>,
  CaptureRevisionHashes: { transcript_revision_kind: true, archived_bytes_sha256: true, source_content_hash: true } satisfies Keys<CaptureRevisionHashes>,
  SessionInventoryNodeResponse: { snapshot_id: true, node_key: true, status: true, node: true } satisfies Keys<SessionInventoryNodeResponse>,
  InventoryNode: { ref: true, evidence: true } satisfies Keys<InventoryNode>,
  InventoryNodeRef: { kind: true, source_instance_id: true, local_id: true, harness: true } satisfies Keys<InventoryNodeRef>,
  Membership: { node: true, run: true, phase_id: true, attempt_id: true, segment: true, confidence: true, evidence: true } satisfies Keys<Membership>,
  LineageEdge: { parent: true, child: true, relation: true, confidence: true, evidence: true, parent_segment: true, child_segment: true } satisfies Keys<LineageEdge>,
  CaptureReceipt: { node: true, availability: true, receipt_sequence: true, evidence: true, destination: true, transcript_revision: true, archived_byte_hash: true } satisfies Keys<CaptureReceipt>,
  InventoryGap: { reason: true, node_keys: true, evidence_ids: true } satisfies Keys<InventoryGap>,
  IdentityBinding: { owner: true, transcript: true, segment: true, confidence: true, evidence: true } satisfies Keys<IdentityBinding>,
  EvidenceRetraction: { target: true, evidence: true } satisfies Keys<EvidenceRetraction>,
} as const;
