import { useEffect, useState } from 'react'

import { getEval, listEvalRuns, type EvalRun, type EvalSummary } from '../api/evals'

export const EVAL_RUNS_PAGE_SIZE = 50

export type EvalDetailState =
  | { kind: 'loading' }
  | { kind: 'error'; message: string }
  | { kind: 'ready'; eval: EvalSummary; runs: EvalRun[]; total: number; page: number; pageSize: number }

/** One eval and one page of its runs, newest first. */
export function useEvalDetail(evalId: string | undefined, page: number): EvalDetailState {
  const [state, setState] = useState<EvalDetailState>({ kind: 'loading' })

  useEffect(() => {
    if (!evalId) return
    let cancelled = false

    Promise.all([getEval(evalId), listEvalRuns(evalId, { page, page_size: EVAL_RUNS_PAGE_SIZE })])
      .then(([summary, runs]) => {
        if (cancelled) return
        setState({
          kind: 'ready',
          eval: summary,
          runs: runs.items,
          total: runs.total,
          page: runs.page,
          pageSize: runs.page_size,
        })
      })
      .catch((err: unknown) => {
        if (!cancelled) setState({ kind: 'error', message: err instanceof Error ? err.message : String(err) })
      })

    return () => {
      cancelled = true
    }
  }, [evalId, page])

  return state
}
