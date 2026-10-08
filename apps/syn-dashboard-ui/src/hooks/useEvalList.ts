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
  | { kind: 'ready'; rows: EvalListRow[]; total: number; page: number; pageSize: number }

async function loadRow(summary: EvalSummary): Promise<EvalListRow> {
  if (summary.run_count === 0) return { eval: summary, recentVerdicts: [] }
  try {
    const runs = await listEvalRuns(summary.eval_id, { page_size: SPARKLINE_RUNS })
    // Runs arrive newest first; a sparkline reads left to right in time.
    return { eval: summary, recentVerdicts: runs.items.map((r) => r.verdict).reverse() }
  } catch {
    return { eval: summary, recentVerdicts: [] }
  }
}

function errorMessage(err: unknown): string {
  return err instanceof Error ? err.message : String(err)
}

/**
 * The eval list, each eval with its latest verdicts.
 *
 * The list response carries only `last_verdict`, so the recent verdicts come
 * from one `/evals/{id}/runs` page per eval on the page. A row whose runs fail
 * to load keeps its summary and draws no sparkline, rather than failing the
 * whole list over a decoration.
 */
export function useEvalList(tag: string | null, page = 1): EvalListState {
  // Keyed by the query it was loaded for, so a new tag or page reads as
  // loading without a synchronous reset inside the effect.
  const key = `${tag ?? ''}|${page}`
  const [loaded, setLoaded] = useState<{ key: string; state: EvalListState } | null>(null)

  useEffect(() => {
    let cancelled = false
    const forKey = `${tag ?? ''}|${page}`

    listEvals({ tag: tag ?? undefined, page })
      .then(async (result) => {
        const rows = await Promise.all(result.evals.map(loadRow))
        const state: EvalListState = {
          kind: 'ready',
          rows,
          total: result.total,
          page: result.page,
          pageSize: result.page_size,
        }
        if (!cancelled) setLoaded({ key: forKey, state })
      })
      .catch((err: unknown) => {
        if (!cancelled) setLoaded({ key: forKey, state: { kind: 'error', message: errorMessage(err) } })
      })

    return () => {
      cancelled = true
    }
  }, [tag, page])

  return loaded && loaded.key === key ? loaded.state : { kind: 'loading' }
}
