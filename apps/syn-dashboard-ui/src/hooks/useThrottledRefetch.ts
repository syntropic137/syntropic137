/**
 * Throttled refetch helper.
 *
 * Wraps a fetcher so calls within `intervalMs` of the last execution are
 * coalesced into a single trailing call. Used by SSE-driven hooks that
 * receive bursts of events but only need to refetch once.
 *
 * See: docs/adrs/ADR-064-observability-monitor-ui.md
 */

import { useCallback, useEffect, useRef } from 'react'

export function useThrottledRefetch(fetcher: () => void, intervalMs: number): () => void {
  const lastFetchRef = useRef<number>(0)
  const pendingTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  const trigger = useCallback(() => {
    const elapsed = Date.now() - lastFetchRef.current
    if (elapsed >= intervalMs) {
      lastFetchRef.current = Date.now()
      fetcher()
      return
    }
    if (pendingTimerRef.current !== null) return
    pendingTimerRef.current = setTimeout(() => {
      pendingTimerRef.current = null
      lastFetchRef.current = Date.now()
      fetcher()
    }, intervalMs - elapsed)
  }, [fetcher, intervalMs])

  useEffect(
    () => () => {
      if (pendingTimerRef.current !== null) {
        clearTimeout(pendingTimerRef.current)
        pendingTimerRef.current = null
      }
    },
    [],
  )

  return trigger
}
