import { useCallback, useEffect, useRef, useState } from 'react'
import { getSession } from '../api/sessions'
import type { SessionResponse } from '../types'
import { useLiveTimer } from './useLiveTimer'
import { RUNNING_POLL_INTERVAL_MS, useSerialRefresh } from './useSerialRefresh'
import { isTerminalSessionStatus } from '../utils/terminalStatus'

export interface UseSessionDataResult {
  session: SessionResponse | null
  loading: boolean
  error: string | null
  now: number
  showConversationLog: boolean
  setShowConversationLog: (show: boolean) => void
}

const FETCH_TIMEOUT_MS = 15_000

function isTerminalSession(s: SessionResponse): boolean {
  return isTerminalSessionStatus(s.status)
}

export function useSessionData(sessionId: string | undefined): UseSessionDataResult {
  const [session, setSession] = useState<SessionResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [showConversationLog, setShowConversationLog] = useState(false)
  const abortRef = useRef<AbortController | null>(null)

  const isRunning = session?.status === 'running'
  const now = useLiveTimer(isRunning)

  // No "cancel the previous request" step: `useSerialRefresh` does not start a
  // second one while the first is outstanding, so there is never a previous
  // request to cancel (#1095). The controller is still how the timeout below
  // and unmount stop a request that IS outstanding.
  const fetchSession = useCallback((): Promise<void> => {
    if (!sessionId) return Promise.resolve()

    const controller = new AbortController()
    abortRef.current = controller

    // Track whether the abort was triggered by our timeout (vs intentional unmount/navigation)
    let didTimeout = false
    const timeoutId = setTimeout(() => {
      didTimeout = true
      controller.abort()
    }, FETCH_TIMEOUT_MS)

    return getSession(sessionId, controller.signal)
      .then((data) => {
        setSession(data)
        setError(null)
        setLoading(false)
      })
      .catch((err) => {
        // Intentional aborts (navigation) — skip all state updates
        if (err.name === 'AbortError' && !didTimeout) return
        setError(didTimeout ? 'Request timed out — the API may be overloaded' : err.message)
        setLoading(false)
      })
      .finally(() => {
        clearTimeout(timeoutId)
      })
  }, [sessionId])

  // Poll while non-terminal; pauses while the tab is hidden (#1048), and never
  // issues a poll on top of one that has not come back (#1095).
  const { refetch } = useSerialRefresh({
    fetch: fetchSession,
    pollIntervalMs: session && !isTerminalSession(session) ? RUNNING_POLL_INTERVAL_MS : null,
  })

  // Initial fetch, and again whenever the session being viewed changes.
  useEffect(() => {
    refetch()
    return () => abortRef.current?.abort()
  }, [refetch, fetchSession])

  return { session, loading, error, now, showConversationLog, setShowConversationLog }
}
