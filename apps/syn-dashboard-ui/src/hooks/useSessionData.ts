import { useCallback, useEffect, useRef, useState } from 'react'
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
const API_BASE = '/api/v1'

async function fetchSessionWithTimeout(sessionId: string, signal?: AbortSignal): Promise<SessionResponse> {
  const response = await fetch(`${API_BASE}/sessions/${sessionId}`, { signal })
  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: response.statusText }))
    throw new Error(error.detail || `API Error: ${response.status}`)
  }
  return response.json()
}

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
    const timeoutId = setTimeout(() => controller.abort(), FETCH_TIMEOUT_MS)

    fetchSessionWithTimeout(sessionId, controller.signal)
      .then((data) => {
        setSession(data)
        setError(null)
      })
      .catch((err) => {
        if (err.name === 'AbortError') {
          setError('Request timed out — the API may be overloaded')
        } else {
          setError(err.message)
        }
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
