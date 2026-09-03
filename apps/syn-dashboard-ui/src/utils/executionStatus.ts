/**
 * Terminal execution statuses — an execution in one of these will never
 * change again, so live views can stop refetching it.
 *
 * Mirrors the backend's terminal set (ExecutionStateMachine.is_terminal in
 * packages/syn-adapters/src/syn_adapters/control/state_machine.py) and the
 * UI's own PROJECTION_TERMINAL_STATES in useExecutionControl. `interrupted`
 * belongs here: the detail projection sets it on WorkflowInterrupted and
 * nothing transitions out of it.
 *
 * Everything else — not_started, running, paused — is still live and worth
 * polling, because Lane 2 numbers (tokens, cost) keep moving.
 */
const TERMINAL_EXECUTION_STATUSES = new Set(['completed', 'failed', 'cancelled', 'interrupted'])

export function isTerminalExecutionStatus(status: string): boolean {
  return TERMINAL_EXECUTION_STATUSES.has(status)
}
