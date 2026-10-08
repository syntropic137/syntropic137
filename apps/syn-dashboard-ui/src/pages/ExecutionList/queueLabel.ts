import type { ExecutionStartQueueInfo } from '../../types'

/**
 * Where a queued start waits and why, e.g. "queued 2 of 3 (4/4 running): slots full 4/4"
 * (PC-124). A queued start has no start time, so this takes the Started slot.
 * Both halves are the server's, so the CLI and the dashboard say the same thing.
 */
export function queueLabel(queue: ExecutionStartQueueInfo): string {
  return `${queue.position_display}: ${queue.reason_display}`
}
