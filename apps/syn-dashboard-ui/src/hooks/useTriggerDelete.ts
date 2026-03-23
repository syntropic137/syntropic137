import { useCallback } from 'react'
import { deleteTrigger, type TriggerSummary } from '../api/triggers'

export function useTriggerDelete(
  setTriggers: React.Dispatch<React.SetStateAction<TriggerSummary[]>>,
  fetchTriggers: (showLoader?: boolean) => void,
  addBusy: (id: string) => void,
  removeBusy: (id: string) => void,
  setActionError: (err: string | null) => void,
) {
  return useCallback(async (triggerId: string) => {
    if (!confirm('Delete this trigger?')) return
    setActionError(null)
    addBusy(triggerId)
    setTriggers((prev) => prev.map((t) => (t.trigger_id === triggerId ? { ...t, status: 'deleted' } : t)))
    try {
      await deleteTrigger(triggerId)
      setTriggers((prev) => prev.filter((t) => t.trigger_id !== triggerId))
    } catch (err) {
      fetchTriggers(false)
      setActionError(err instanceof Error ? err.message : 'Failed to delete trigger')
    } finally {
      removeBusy(triggerId)
    }
  }, [setTriggers, fetchTriggers, addBusy, removeBusy, setActionError])
}
