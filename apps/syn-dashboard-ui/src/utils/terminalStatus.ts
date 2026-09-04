/**
 * Which statuses mean "this will never change again".
 *
 * Every live view in the dashboard polls until whatever it is showing reaches a
 * terminal status. That decision used to be four separate literal sets, one per
 * hook, and they drifted: the two execution hooks were both missing
 * `interrupted`, so a forcibly stopped run polled the API every 3 seconds for as
 * long as the tab stayed open (#1048). The sets looked identical, which is
 * exactly why nobody noticed one enum had grown a seventh member.
 *
 * Callers ask "is this done?" and are not told how that is decided, so adding a
 * status to a domain enum is a one-line change here rather than a hunt through
 * the hooks.
 *
 * Executions and sessions have genuinely different vocabularies, so they get
 * separate predicates rather than one union that would accept a session status
 * for an execution:
 *
 * | Domain enum       | Source                                                          |
 * |-------------------|-----------------------------------------------------------------|
 * | `ExecutionStatus` | `orchestration/domain/aggregate_execution/value_objects.py`      |
 * | `SessionStatus`   | `agent_sessions/_shared/value_objects.py`                        |
 */

/**
 * `ExecutionStatus`, minus the states an execution can still leave.
 *
 * The full enum is `not_started | running | paused | completed | failed |
 * cancelled | interrupted`. The first three are non-terminal: `paused` and
 * `not_started` both resume, so a view that stopped polling on them would go
 * stale the moment the run picked back up.
 *
 * `interrupted` is written by the execution-detail projection on
 * `WorkflowInterrupted` (a forceful SIGINT stop) and never transitions again.
 */
const TERMINAL_EXECUTION_STATUSES: ReadonlySet<string> = new Set([
  'completed',
  'failed',
  'cancelled',
  'interrupted',
])

/**
 * `SessionStatus`, minus `running`.
 *
 * Deliberately not the same set as the execution one: `SessionStatus` has only
 * four members and no `interrupted`, so folding the two together would make
 * this set claim to know about a status agent sessions cannot produce.
 */
const TERMINAL_SESSION_STATUSES: ReadonlySet<string> = new Set([
  'completed',
  'failed',
  'cancelled',
])

/** True when a workflow execution has reached a state it cannot leave. */
export function isTerminalExecutionStatus(status: string): boolean {
  return TERMINAL_EXECUTION_STATUSES.has(status)
}

/** True when an agent session has reached a state it cannot leave. */
export function isTerminalSessionStatus(status: string): boolean {
  return TERMINAL_SESSION_STATUSES.has(status)
}
