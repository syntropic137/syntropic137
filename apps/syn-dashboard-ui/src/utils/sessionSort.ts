/**
 * Pure sort utilities for SessionSummary lists.
 *
 * Comparators are exported in a Record keyed by SortKey so the call site
 * can dispatch without a switch (keeps cyclomatic complexity low).
 */

import type { SessionSummary } from '../types'
import type { SortDir, SortKey } from '../hooks/useSortUrlState'

type Cmp = (a: SessionSummary, b: SessionSummary) => number

function cmpString(a: string | null | undefined, b: string | null | undefined): number {
  return (a ?? '').localeCompare(b ?? '')
}

function cmpNumber(a: number | null | undefined, b: number | null | undefined): number {
  const av = a ?? Number.NEGATIVE_INFINITY
  const bv = b ?? Number.NEGATIVE_INFINITY
  return av - bv
}

function workflowLabel(s: SessionSummary): string {
  return s.workflow_name ?? s.workflow_id ?? ''
}

const COMPARATORS: Record<SortKey, Cmp> = {
  status: (a, b) => cmpString(a.status, b.status),
  workflow: (a, b) => cmpString(workflowLabel(a), workflowLabel(b)),
  phase: (a, b) => cmpString(a.phase_id, b.phase_id),
  model: (a, b) => cmpString(a.agent_model, b.agent_model),
  tokens: (a, b) => cmpNumber(a.total_tokens, b.total_tokens),
  cost: (a, b) => cmpNumber(a.total_cost_usd, b.total_cost_usd),
  duration: (a, b) => cmpNumber(a.duration_seconds, b.duration_seconds),
  started: (a, b) => cmpString(a.started_at, b.started_at),
}

export function sortSessions(
  sessions: SessionSummary[],
  key: SortKey,
  dir: SortDir,
): SessionSummary[] {
  const cmp = COMPARATORS[key]
  const sign = dir === 'asc' ? 1 : -1
  return [...sessions].sort((a, b) => sign * cmp(a, b))
}
