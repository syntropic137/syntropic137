import { useEffect, useState } from 'react'

import { listEvalRuns, listEvals, type EvalSummary, type EvalVerdict } from '../api/evals'

/** How many of an eval's latest verdicts its sparkline shows. */
export const SPARKLINE_RUNS = 12

export interface EvalListRow {
  eval: EvalSummary
  /** Verdicts of the latest runs, oldest first; null for a run not yet scored. */
  recentVerdicts: (EvalVerdict | null)[]
}

export type EvalListState =
  | { kind: 'loading' }
  | { kind: 'error'; message: string }
  | { kind: 'ready'; rows: EvalListRow[]; total: number }

/**
 * The eval list, each eval with its latest verdicts.
 *
 * The list response carries only `last_verdict`, so the recent verdicts come
 * from one `/evals/{id}/runs` page per eval on the page. A row whose runs fail
 * to load keeps its summary and draws no sparkline, rather than failing the
 * whole list over a decoration.
 */
export function useEvalList(tag: string | null): EvalListState {
  // Keyed by the tag it was loaded for, so a new tag reads as loading without
  // a synchronous reset inside the effect.
  const [loaded, setLoaded] = useState<{ tag: string | null; state: EvalListState } | null>(null)

  useEffect(() => {
    let cancelled = false

    listEvals({ tag: tag ?? undefined })
      .then(async (page) => {
        const rows = await Promise.all(
          page.evals.map(async (summary): Promise<EvalListRow> => {
            if (summary.run_count === 0) return { eval: summary, recentVerdicts: [] }
            try {
              const runs = await listEvalRuns(summary.eval_id, { page_size: SPARKLINE_RUNS })
              // Runs arrive newest first; a sparkline reads left to right in time.
              return { eval: summary, recentVerdicts: runs.items.map((r) => r.verdict).reverse() }
            } catch {
              return { eval: summary, recentVerdicts: [] }
            }
          }),
        )
        if (!cancelled) setLoaded({ tag, state: { kind: 'ready', rows, total: page.total } })
      })
      .catch((err: unknown) => {
        if (!cancelled) setLoaded({ tag, state: { kind: 'error', message: err instanceof Error ? err.message : String(err) } })
      })

    return () => {
      cancelled = true
    }
  }, [tag])

  return loaded && loaded.tag === tag ? loaded.state : { kind: 'loading' }
}
