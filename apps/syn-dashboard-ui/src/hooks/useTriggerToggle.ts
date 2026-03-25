import { useCallback } from 'react'
import { updateTrigger, type TriggerSummary } from '../api/triggers'

function resolveAction(status: string): { action: 'pause' | 'resume'; newStatus: string } {
  const action = status === 'active' ? 'pause' as const : 'resume' as const
  const newStatus = action === 'pause' ? 'paused' : 'active'
  return { action, newStatus }
}

function patchTriggerStatus(
  setTriggers: React.Dispatch<React.SetStateAction<TriggerSummary[]>>,
  triggerId: string,
  status: string,
) {
  setTriggers((prev) => prev.map((t) => (t.trigger_id === triggerId ? { ...t, status } : t)))
}

export function useTriggerToggle(
  setTriggers: React.Dispatch<React.SetStateAction<TriggerSummary[]>>,
  fetchTriggers: (showLoader?: boolean) => void,
  addBusy: (id: string) => void,
  removeBusy: (id: string) => void,
  setActionError: (err: string | null) => void,
) {
  return useCallback(async (trigger: TriggerSummary) => {
    const { action, newStatus } = resolveAction(trigger.status)
    setActionError(null)
    addBusy(trigger.trigger_id)
    patchTriggerStatus(setTriggers, trigger.trigger_id, newStatus)
    try {
      await updateTrigger(trigger.trigger_id, action)
      fetchTriggers(false)
    } catch (err) {
      patchTriggerStatus(setTriggers, trigger.trigger_id, trigger.status)
      setActionError(err instanceof Error ? err.message : `Failed to ${action} trigger`)
    } finally {
      removeBusy(trigger.trigger_id)
    }
  }, [setTriggers, fetchTriggers, addBusy, removeBusy, setActionError])
}
