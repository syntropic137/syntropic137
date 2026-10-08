import { useEffect, useState } from 'react'

import { listEvalRuns, type EvalRun } from '../api/evals'

/** The largest page `/evals/{id}/runs` serves (`MAX_PAGE_SIZE` in syn-api). */
export const TIMELINE_PAGE_SIZE = 200

/** A bound on how far back the timeline reads, so one eval cannot page forever. */
export const TIMELINE_MAX_RUNS = 2000

export type EvalTimelineState =
  | { kind: 'loading' }
  | { kind: 'error'; message: string }
  | { kind: 'ready'; runs: EvalRun[]; total: number }

/** Every run of an eval, newest first, read page by page up to the bound. */
export async function loadEvalTimeline(evalId: string): Promise<{ runs: EvalRun[]; total: number }> {
  const runs: EvalRun[] = []
  let total = 0
  for (let page = 1; runs.length < TIMELINE_MAX_RUNS; page++) {
    const res = await listEvalRuns(evalId, { page, page_size: TIMELINE_PAGE_SIZE })
    total = res.total
    runs.push(...res.items)
    // A short page is the last one, whatever `total` said when it was read.
    if (res.items.length < TIMELINE_PAGE_SIZE || runs.length >= total) break
  }
  return { runs, total }
}

/**
 * The history the timeline draws. It is read on its own, independent of the
 * runs table's page, so paging the table never changes the chart.
 */
export function useEvalTimeline(evalId: string | undefined): EvalTimelineState {
  const [loaded, setLoaded] = useState<{ evalId: string; state: EvalTimelineState } | null>(null)

  useEffect(() => {
    if (!evalId) return
    let cancelled = false

    loadEvalTimeline(evalId)
      .then(({ runs, total }) => {
        if (!cancelled) setLoaded({ evalId, state: { kind: 'ready', runs, total } })
      })
      .catch((err: unknown) => {
        const message = err instanceof Error ? err.message : String(err)
        if (!cancelled) setLoaded({ evalId, state: { kind: 'error', message } })
      })

    return () => {
      cancelled = true
    }
  }, [evalId])

  return loaded && loaded.evalId === evalId ? loaded.state : { kind: 'loading' }
}
