/**
 * How full the execution budget is, kept current for the app bar (PC-124).
 *
 * The list endpoint reports the budget beside every page, so this asks it for
 * one row and keeps only the budget. Polled like the server build: no SSE
 * event carries a slot being taken or a start queueing.
 *
 * A failed fetch keeps the last answer rather than claiming an empty queue.
 */

import { useCallback, useEffect, useState } from 'react'

import { getExecutionBudget } from '../api'
import type { ExecutionBudgetInfo } from '../types'
import { ifStillWanted } from './serialRefreshLoop'
import { useSerialRefresh } from './useSerialRefresh'

export const BUDGET_POLL_INTERVAL_MS = 15_000

export function useExecutionBudget(): ExecutionBudgetInfo | null {
  const [budget, setBudget] = useState<ExecutionBudgetInfo | null>(null)

  const fetchBudget = useCallback(
    (signal: AbortSignal): Promise<void> =>
      getExecutionBudget(signal).then(ifStillWanted(signal, setBudget)),
    [],
  )

  const { refetch } = useSerialRefresh({ fetch: fetchBudget, pollIntervalMs: BUDGET_POLL_INTERVAL_MS })

  useEffect(() => {
    refetch()
  }, [refetch])

  return budget
}
