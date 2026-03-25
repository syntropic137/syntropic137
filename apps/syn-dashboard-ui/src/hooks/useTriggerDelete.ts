import { useCallback } from 'react'
import { deleteTrigger, type TriggerSummary } from '../api/triggers'

function markAsDeleted(triggers: TriggerSummary[], triggerId: string): TriggerSummary[] {
  return triggers.map((t) => (t.trigger_id === triggerId ? { ...t, status: 'deleted' } : t))
}

function removeById(triggers: TriggerSummary[], triggerId: string): TriggerSummary[] {
  return triggers.filter((t) => t.trigger_id !== triggerId)
}

function extractErrorMessage(err: unknown): string {
  return err instanceof Error ? err.message : 'Failed to delete trigger'
}

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
    setTriggers((prev) => markAsDeleted(prev, triggerId))
    try {
      await deleteTrigger(triggerId)
      setTriggers((prev) => removeById(prev, triggerId))
    } catch (err) {
      fetchTriggers(false)
      setActionError(extractErrorMessage(err))
    } finally {
      removeBusy(triggerId)
    }
  }, [setTriggers, fetchTriggers, addBusy, removeBusy, setActionError])
}
