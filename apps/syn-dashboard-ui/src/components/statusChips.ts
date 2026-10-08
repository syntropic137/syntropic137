/** The status chips a list offers, in order (PC-124: executions add `queued`). */

export interface StatusChip {
  value: string
  label: string
}

export const DEFAULT_STATUSES: readonly StatusChip[] = [
  { value: 'pending', label: 'Pending' },
  { value: 'running', label: 'Running' },
  { value: 'completed', label: 'Completed' },
  { value: 'failed', label: 'Failed' },
  { value: 'cancelled', label: 'Cancelled' },
]
