/**
 * Polls a refetch callback while at least one item is non-terminal.
 *
 * SSE only fires on lifecycle transitions (Started/Completed). Lane 2
 * (cost, tokens, duration) updates continuously while an agent runs, so
 * we poll a short cadence to keep those numbers ticking without manual
 * refresh. Pauses when the tab is hidden; refetches once on resume.
 */

import { useEffect, useMemo } from 'react'

interface Options<T> {
  items: T[]
  isTerminal: (item: T) => boolean
  refetch: () => void
  intervalMs?: number
}

const DEFAULT_INTERVAL_MS = 3000

export function useRefetchWhileRunning<T>({
  items,
  isTerminal,
  refetch,
  intervalMs = DEFAULT_INTERVAL_MS,
}: Options<T>): void {
  const hasRunning = useMemo(() => items.some((item) => !isTerminal(item)), [items, isTerminal])

  useEffect(() => {
    if (!hasRunning) return
    const tick = () => {
      if (typeof document === 'undefined' || document.visibilityState === 'visible') {
        refetch()
      }
    }
    const id = setInterval(tick, intervalMs)
    const onVisibility = () => {
      if (document.visibilityState === 'visible') refetch()
    }
    document.addEventListener('visibilitychange', onVisibility)
    return () => {
      clearInterval(id)
      document.removeEventListener('visibilitychange', onVisibility)
    }
  }, [hasRunning, refetch, intervalMs])
}
