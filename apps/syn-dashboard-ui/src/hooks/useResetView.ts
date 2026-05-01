/**
 * Single-call reset for filter + sort URL params shared by Sessions / Executions.
 *
 * Two back-to-back setSearchParams calls in react-router-dom v6 collapse, so
 * the second overwrites the first. This hook does one update that wipes
 * status, timeWindow, sort, and dir at the same time, and returns a stable
 * callback the page can pass to ResourceFilterBar.
 */

import { useCallback } from 'react'
import { useSearchParams } from 'react-router-dom'

const VIEW_PARAMS_TO_CLEAR = ['status', 'timeWindow', 'sort', 'dir']

export function useResetView(): () => void {
  const [, setSearchParams] = useSearchParams()
  return useCallback(() => {
    setSearchParams(
      (prev) => {
        const out = new URLSearchParams(prev)
        for (const key of VIEW_PARAMS_TO_CLEAR) out.delete(key)
        return out
      },
      { replace: true },
    )
  }, [setSearchParams])
}
