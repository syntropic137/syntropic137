import { useCallback, useEffect, useState } from 'react'
import { getSession } from '../api/sessions'
import type { SessionResponse } from '../types'
import { ifStillWanted } from './serialRefreshLoop'
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

  const isRunning = session?.status === 'running'
  const now = useLiveTimer(isRunning)

  // No "cancel the previous request" step, and no controller of its own for
  // navigating away: `useSerialRefresh` never has two outstanding at once, and
  // it aborts the one it abandons when the session being viewed changes or the
  // view unmounts (#1095). What is left here is the one reason to give up that
  // the loop cannot know about - the server taking too long - so this
  // controller exists for the timeout and is chained to the loop's signal.
  const fetchSession = useCallback(
    (signal: AbortSignal): Promise<void> => {
      if (!sessionId) return Promise.resolve()

      const controller = new AbortController()
      signal.addEventListener('abort', () => controller.abort())

      // Which of the two aborted it decides whether the user hears about it.
      let didTimeout = false
      const timeoutId = setTimeout(() => {
        didTimeout = true
        controller.abort()
      }, FETCH_TIMEOUT_MS)

      return getSession(sessionId, controller.signal)
        .then(
          ifStillWanted(signal, (data: SessionResponse) => {
            setSession(data)
            setError(null)
            setLoading(false)
          }),
        )
        // Abandoned by the loop: not a failure, and about a session nobody is
        // looking at any more - so the wrapper covers this handler too.
        .catch(
          ifStillWanted(signal, (err: Error) => {
            setError(didTimeout ? 'Request timed out — the API may be overloaded' : err.message)
            setLoading(false)
          }),
        )
        // Not wrapped: the timer has to be cleared whatever the answer was.
        .finally(() => {
          clearTimeout(timeoutId)
        })
    },
    [sessionId],
  )

  // Poll while non-terminal; pauses while the tab is hidden (#1048), and never
  // issues a poll on top of one that has not come back (#1095).
  const { refetch } = useSerialRefresh({
    fetch: fetchSession,
    pollIntervalMs: session && !isTerminalSession(session) ? RUNNING_POLL_INTERVAL_MS : null,
  })

  // Initial fetch, and again whenever the session being viewed changes.
  useEffect(() => {
    refetch()
  }, [refetch, fetchSession])

  return { session, loading, error, now, showConversationLog, setShowConversationLog }
}
