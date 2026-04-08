import { useCallback, useEffect, useRef, useState } from 'react'
import { getSession } from '../api/sessions'
import type { SessionResponse } from '../types'
import { useLiveTimer } from './useLiveTimer'
import { usePolling } from './usePolling'

export interface UseSessionDataResult {
  session: SessionResponse | null
  loading: boolean
  error: string | null
  now: number
  showConversationLog: boolean
  setShowConversationLog: (show: boolean) => void
}

const FETCH_TIMEOUT_MS = 15_000

export function useSessionData(sessionId: string | undefined): UseSessionDataResult {
  const [session, setSession] = useState<SessionResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [showConversationLog, setShowConversationLog] = useState(false)
  const abortRef = useRef<AbortController | null>(null)

  const isRunning = session?.status === 'running'
  const now = useLiveTimer(isRunning)

  const fetchSession = useCallback(() => {
    if (!sessionId) return

    // Cancel any in-flight request
    abortRef.current?.abort()
    const controller = new AbortController()
    abortRef.current = controller

    // Track whether the abort was triggered by our timeout (vs intentional unmount/navigation)
    let didTimeout = false
    const timeoutId = setTimeout(() => {
      didTimeout = true
      controller.abort()
    }, FETCH_TIMEOUT_MS)

    getSession(sessionId, controller.signal)
      .then((data) => {
        setSession(data)
        setError(null)
      })
      .catch((err) => {
        // Intentional aborts (navigation, new fetch cycle) — silent
        if (err.name === 'AbortError' && !didTimeout) return
        setError(didTimeout ? 'Request timed out — the API may be overloaded' : err.message)
      })
      .finally(() => {
        clearTimeout(timeoutId)
        setLoading(false)
      })
  }, [sessionId])

  // Initial fetch
  useEffect(() => {
    fetchSession()
    return () => abortRef.current?.abort()
  }, [fetchSession])

  // Poll while running
  usePolling(fetchSession, 2000, isRunning)

  return { session, loading, error, now, showConversationLog, setShowConversationLog }
}
