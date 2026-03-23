import { useCallback } from 'react'
import { updateTrigger, type TriggerSummary } from '../api/triggers'

export function useTriggerToggle(
  setTriggers: React.Dispatch<React.SetStateAction<TriggerSummary[]>>,
  fetchTriggers: (showLoader?: boolean) => void,
  addBusy: (id: string) => void,
  removeBusy: (id: string) => void,
  setActionError: (err: string | null) => void,
) {
  return useCallback(async (trigger: TriggerSummary) => {
    const action = trigger.status === 'active' ? 'pause' : 'resume'
    const newStatus = action === 'pause' ? 'paused' : 'active'
    setActionError(null)
    addBusy(trigger.trigger_id)
    const patchStatus = (status: string) =>
      setTriggers((prev) => prev.map((t) => (t.trigger_id === trigger.trigger_id ? { ...t, status } : t)))
    patchStatus(newStatus)
    try {
      await updateTrigger(trigger.trigger_id, action)
      fetchTriggers(false)
    } catch (err) {
      patchStatus(trigger.status)
      setActionError(err instanceof Error ? err.message : `Failed to ${action} trigger`)
    } finally {
      removeBusy(trigger.trigger_id)
    }
  }, [setTriggers, fetchTriggers, addBusy, removeBusy, setActionError])
}
