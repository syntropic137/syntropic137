/**
 * Every `event_type` the API's live streams emit, checked in so a new one is a
 * deliberate change here (and a failing contract test until it is mapped in
 * invalidate.ts), never a frame that silently invalidates nothing.
 *
 * Source of truth (Syntropic137 repo):
 * - packages/syn-adapters/src/syn_adapters/projections/realtime.py:
 *   RealTimeProjection.on_* handlers. `_forward_event` names go to the
 *   per-execution stream; `broadcast_global` names also go to /sse/activity.
 * - apps/syn-api/src/syn_api/routes/webhooks/push_events.py: `git_commit`
 *   (activity only).
 * - apps/syn-api/src/syn_api/routes/sse.py: the `connected` handshake, a
 *   frame of type 'connected' that carries no domain event.
 *
 * The name is in the JSON payload's `event_type` field (no SSE `event:` line).
 */

/** On the global activity stream (/sse/activity), which drives cache invalidation. */
export const ACTIVITY_EVENT_TYPES = [
  'WorkflowExecutionStarted',
  'WorkflowCompleted',
  'WorkflowFailed',
  'SessionStarted',
  'SessionCompleted',
  'git_commit',
] as const

/** Only on a per-execution stream (/sse/executions/{id}). */
export const EXECUTION_STREAM_EVENT_TYPES = [
  'PhaseStarted',
  'PhaseCompleted',
  'OperationRecorded',
  'ArtifactCreated',
  'SubagentStarted',
  'SubagentStopped',
] as const

export type ActivityEventType = (typeof ACTIVITY_EVENT_TYPES)[number]
export type ExecutionStreamEventType = (typeof EXECUTION_STREAM_EVENT_TYPES)[number]
export type LiveEventType = ActivityEventType | ExecutionStreamEventType

export const LIVE_EVENT_TYPES: readonly LiveEventType[] = [...ACTIVITY_EVENT_TYPES, ...EXECUTION_STREAM_EVENT_TYPES]

const RUN = new Set<string>(['WorkflowExecutionStarted', 'WorkflowCompleted', 'WorkflowFailed', 'PhaseStarted', 'PhaseCompleted'])
const SESSION = new Set<string>(['SessionStarted', 'SessionCompleted', 'OperationRecorded', 'SubagentStarted', 'SubagentStopped'])

/** A workflow execution or one of its phases changed. */
export const isRunEvent = (eventType: string): boolean => RUN.has(eventType)
/** An execution reached a terminal state. */
export const isRunFinished = (eventType: string): boolean => eventType === 'WorkflowCompleted' || eventType === 'WorkflowFailed'
/** An agent session (or its operations / subagents) changed. */
export const isSessionEvent = (eventType: string): boolean => SESSION.has(eventType)
/** An artifact was stored. */
export const isArtifactEvent = (eventType: string): boolean => eventType === 'ArtifactCreated'
/** A repo-level git event (activity stream). */
export const isGitEvent = (eventType: string): boolean => eventType.startsWith('git_')
