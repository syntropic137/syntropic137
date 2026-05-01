/**
 * Pure sort utilities for ExecutionListItem lists.
 *
 * Mirrors sessionSort: comparators in a Record keyed by ExecutionSortKey so
 * the call site can dispatch without a switch (keeps cyclomatic complexity
 * low).
 */

import type { ExecutionListItem } from '../types'
import type { ExecutionSortKey } from '../hooks/useExecutionList'
import type { SortDir } from '../hooks/useSortUrlState'

type Cmp = (a: ExecutionListItem, b: ExecutionListItem) => number

function cmpString(a: string | null | undefined, b: string | null | undefined): number {
  return (a ?? '').localeCompare(b ?? '')
}

function cmpNumber(a: number | null | undefined, b: number | null | undefined): number {
  const av = a ?? Number.NEGATIVE_INFINITY
  const bv = b ?? Number.NEGATIVE_INFINITY
  return av - bv
}

function workflowLabel(e: ExecutionListItem): string {
  return e.workflow_name || e.workflow_id
}

function progressFraction(e: ExecutionListItem): number {
  return e.total_phases > 0 ? e.completed_phases / e.total_phases : 0
}

const COMPARATORS: Record<ExecutionSortKey, Cmp> = {
  status: (a, b) => cmpString(a.status, b.status),
  workflow: (a, b) => cmpString(workflowLabel(a), workflowLabel(b)),
  progress: (a, b) => cmpNumber(progressFraction(a), progressFraction(b)),
  tokens: (a, b) => cmpNumber(a.total_tokens, b.total_tokens),
  cost: (a, b) => cmpNumber(a.total_cost_usd, b.total_cost_usd),
  duration: (a, b) => cmpNumber(a.duration_seconds, b.duration_seconds),
  repos: (a, b) => cmpString(a.repos_display, b.repos_display),
  started: (a, b) => cmpString(a.started_at, b.started_at),
}

export function sortExecutions(
  rows: ExecutionListItem[],
  key: ExecutionSortKey,
  dir: SortDir,
): ExecutionListItem[] {
  const cmp = COMPARATORS[key]
  const sign = dir === 'asc' ? 1 : -1
  return [...rows].sort((a, b) => sign * cmp(a, b))
}
