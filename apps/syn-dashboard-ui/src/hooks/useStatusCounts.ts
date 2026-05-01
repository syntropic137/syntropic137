/**
 * Memoised count of items per status, used to label filter chips.
 *
 * Generic over any item shape that has a `.status` string, so Sessions
 * and Executions can share this hook.
 *
 * See: docs/adrs/ADR-064-observability-monitor-ui.md
 */

import { useMemo } from 'react'

export function useStatusCounts(items: { status: string }[]): Record<string, number> {
  return useMemo(() => {
    const counts: Record<string, number> = {}
    for (const item of items) {
      counts[item.status] = (counts[item.status] ?? 0) + 1
    }
    return counts
  }, [items])
}
