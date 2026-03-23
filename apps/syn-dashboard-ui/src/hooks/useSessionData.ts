import { useCallback, useEffect, useState } from 'react'
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

export function useSessionData(sessionId: string | undefined): UseSessionDataResult {
  const [session, setSession] = useState<SessionResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [showConversationLog, setShowConversationLog] = useState(false)

  const isRunning = session?.status === 'running'
  const now = useLiveTimer(isRunning)

  const fetchSession = useCallback(() => {
    if (!sessionId) return
    getSession(sessionId)
      .then((data) => setSession(data))
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false))
  }, [sessionId])

  // Initial fetch
  useEffect(() => {
    fetchSession()
  }, [fetchSession])

  // Poll while running
  usePolling(fetchSession, 2000, isRunning)

  return { session, loading, error, now, showConversationLog, setShowConversationLog }
}
