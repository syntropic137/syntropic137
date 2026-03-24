import { useEffect, useState } from 'react'

import {
  getTrigger,
  getTriggerHistory,
  type TriggerDetail,
  type TriggerHistoryEntry,
} from '../api/client'

export interface UseTriggerDataResult {
  trigger: TriggerDetail | null
  history: TriggerHistoryEntry[]
  loading: boolean
  error: string | null
}

/**
 * Fetch trigger detail and firing history for a given trigger ID.
 */
export function useTriggerData(triggerId: string | undefined): UseTriggerDataResult {
  const [trigger, setTrigger] = useState<TriggerDetail | null>(null)
  const [history, setHistory] = useState<TriggerHistoryEntry[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!triggerId) return

    let cancelled = false
    Promise.all([getTrigger(triggerId), getTriggerHistory(triggerId)])
      .then(([t, h]) => {
        if (cancelled) return
        setTrigger(t)
        setHistory(h.entries)
      })
      .catch((err) => {
        if (!cancelled) setError(err instanceof Error ? err.message : 'Failed to load trigger')
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => { cancelled = true }
  }, [triggerId])

  return { trigger, history, loading, error }
}
