/**
 * Memoised count of sessions per status, used to label filter chips.
 *
 * See: docs/adrs/ADR-064-observability-monitor-ui.md
 */

import { useMemo } from 'react'
import type { SessionSummary } from '../types'

export function useStatusCounts(sessions: SessionSummary[]): Record<string, number> {
  return useMemo(() => {
    const counts: Record<string, number> = {}
    for (const session of sessions) {
      counts[session.status] = (counts[session.status] ?? 0) + 1
    }
    return counts
  }, [sessions])
}
