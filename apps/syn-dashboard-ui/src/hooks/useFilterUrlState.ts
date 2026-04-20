/**
 * URL-backed state for the Sessions filter bar.
 *
 * Source of truth is the URL — all state derives from `useSearchParams`. Set
 * helpers write back via `setSearchParams({ replace: true })` so filter
 * changes do not pollute browser history.
 *
 * Schema: `?status=running,failed&timeWindow=24h`
 *
 * See: docs/adrs/ADR-064-observability-monitor-ui.md
 */

import { useCallback, useMemo } from 'react'
import { useSearchParams } from 'react-router-dom'
import type { TimeWindow } from '../types'

const VALID_TIME_WINDOWS: TimeWindow[] = ['15m', '1h', '24h', '7d', 'all']
const DEFAULT_TIME_WINDOW: TimeWindow = '24h'

function parseStatuses(raw: string | null): Set<string> {
  if (!raw) return new Set()
  return new Set(raw.split(',').map((s) => s.trim()).filter(Boolean))
}

function parseTimeWindow(raw: string | null): TimeWindow {
  return VALID_TIME_WINDOWS.includes(raw as TimeWindow)
    ? (raw as TimeWindow)
    : DEFAULT_TIME_WINDOW
}

function withStatuses(prev: URLSearchParams, next: Set<string>): URLSearchParams {
  const out = new URLSearchParams(prev)
  if (next.size === 0) out.delete('status')
  else out.set('status', Array.from(next).sort().join(','))
  return out
}

function withTimeWindow(prev: URLSearchParams, next: TimeWindow): URLSearchParams {
  const out = new URLSearchParams(prev)
  if (next === DEFAULT_TIME_WINDOW) out.delete('timeWindow')
  else out.set('timeWindow', next)
  return out
}

function withCleared(prev: URLSearchParams): URLSearchParams {
  const out = new URLSearchParams(prev)
  out.delete('status')
  out.delete('timeWindow')
  return out
}

function toggleInSet(set: Set<string>, value: string): Set<string> {
  const next = new Set(set)
  if (next.has(value)) next.delete(value)
  else next.add(value)
  return next
}

export interface FilterUrlState {
  selectedStatuses: Set<string>
  timeWindow: TimeWindow
  toggleStatus: (status: string) => void
  setTimeWindow: (next: TimeWindow) => void
  clearStatuses: () => void
  clearAll: () => void
}

export function useFilterUrlState(): FilterUrlState {
  const [searchParams, setSearchParams] = useSearchParams()

  const selectedStatuses = useMemo(
    () => parseStatuses(searchParams.get('status')),
    [searchParams],
  )
  const timeWindow = useMemo(
    () => parseTimeWindow(searchParams.get('timeWindow')),
    [searchParams],
  )

  const writeStatuses = useCallback(
    (next: Set<string>) => {
      setSearchParams((prev) => withStatuses(prev, next), { replace: true })
    },
    [setSearchParams],
  )

  const toggleStatus = useCallback(
    (status: string) => writeStatuses(toggleInSet(selectedStatuses, status)),
    [selectedStatuses, writeStatuses],
  )

  const setTimeWindow = useCallback(
    (next: TimeWindow) => {
      setSearchParams((prev) => withTimeWindow(prev, next), { replace: true })
    },
    [setSearchParams],
  )

  const clearStatuses = useCallback(() => writeStatuses(new Set()), [writeStatuses])

  const clearAll = useCallback(() => {
    setSearchParams((prev) => withCleared(prev), { replace: true })
  }, [setSearchParams])

  return {
    selectedStatuses,
    timeWindow,
    toggleStatus,
    setTimeWindow,
    clearStatuses,
    clearAll,
  }
}

/** Resolve a TimeWindow into an ISO 8601 lower bound (or undefined for 'all'). */
export function timeWindowToStartedAfter(
  window: TimeWindow,
  now: Date = new Date(),
): string | undefined {
  switch (window) {
    case '15m':
      return new Date(now.getTime() - 15 * 60 * 1000).toISOString()
    case '1h':
      return new Date(now.getTime() - 60 * 60 * 1000).toISOString()
    case '24h':
      return new Date(now.getTime() - 24 * 60 * 60 * 1000).toISOString()
    case '7d':
      return new Date(now.getTime() - 7 * 24 * 60 * 60 * 1000).toISOString()
    case 'all':
      return undefined
  }
}
