import { useState } from 'react'
import type { TriggerSummary } from '../api/triggers'
import { useBusyTracker } from './useBusyTracker'
import { useTriggerDelete } from './useTriggerDelete'
import { useTriggerToggle } from './useTriggerToggle'

export interface UseTriggerActionsResult {
  handleToggle: (trigger: TriggerSummary) => Promise<void>
  handleDelete: (triggerId: string) => Promise<void>
  busyIds: Set<string>
  actionError: string | null
  clearError: () => void
}

export function useTriggerActions(
  _triggers: TriggerSummary[],
  setTriggers: React.Dispatch<React.SetStateAction<TriggerSummary[]>>,
  fetchTriggers: (showLoader?: boolean) => void,
): UseTriggerActionsResult {
  const [actionError, setActionError] = useState<string | null>(null)
  const { busyIds, addBusy, removeBusy } = useBusyTracker()

  const handleToggle = useTriggerToggle(setTriggers, fetchTriggers, addBusy, removeBusy, setActionError)
  const handleDelete = useTriggerDelete(setTriggers, fetchTriggers, addBusy, removeBusy, setActionError)

  return { handleToggle, handleDelete, busyIds, actionError, clearError: () => setActionError(null) }
}
