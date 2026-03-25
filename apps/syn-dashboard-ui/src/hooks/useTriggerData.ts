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

function extractErrorMessage(err: unknown): string {
  return err instanceof Error ? err.message : 'Failed to load trigger'
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

    const applyResult = ([t, h]: [TriggerDetail, { entries: TriggerHistoryEntry[] }]) => {
      if (cancelled) return
      setTrigger(t)
      setHistory(h.entries)
    }

    const applyError = (err: unknown) => {
      if (!cancelled) setError(extractErrorMessage(err))
    }

    const applyFinally = () => {
      if (!cancelled) setLoading(false)
    }

    Promise.all([getTrigger(triggerId), getTriggerHistory(triggerId)])
      .then(applyResult)
      .catch(applyError)
      .finally(applyFinally)

    return () => { cancelled = true }
  }, [triggerId])

  return { trigger, history, loading, error }
}
