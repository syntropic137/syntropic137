/**
 * Cache names for every resource read, and the one way to invalidate them.
 *
 * Names are the resource function's name, as a type-only union: a typo is a
 * compile error and nothing ships at runtime. `QueryTarget` addresses every
 * entry of a resource, or only those whose first parameter is `id` (detail
 * reads take their id first).
 */
import { type QueryCache, type QueryGetOptions, queryCache } from './client/queryCache'

export type ResourceName =
  | 'listWorkflows' | 'getWorkflow' | 'getWorkflowHistory'
  | 'listWorkflowRuns' | 'getExecution' | 'listExecutions' | 'getExecutionBudget'
  | 'listSessions' | 'getSession'
  | 'getSessionInventory' | 'getSessionInventoryPage' | 'getSessionInventoryNode'
  | 'listEvals' | 'getEval' | 'listEvalRuns' | 'listEvalExecutions'
  | 'listArtifacts' | 'getArtifact' | 'getArtifactContent'
  | 'listTriggers' | 'getTrigger' | 'getTriggerHistory'
  | 'listRepos' | 'listSystems' | 'lookUpAppAccess'
  | 'listSessionCosts' | 'getSessionCost' | 'listExecutionCosts' | 'getExecutionCost' | 'getCostSummary'
  | 'getMetrics' | 'getToolTimeline' | 'getTokenMetrics' | 'getConversationLog' | 'getSSEHealth' | 'getFeatures' | 'getBuildInfo'
  | 'getContributionHeatmap'
  | 'getEvalTrend' | 'getWorkflowTrend'
  | 'getWorkflowLatestOutputs'

export interface QueryTarget {
  name: ResourceName
  /** Only entries whose first parameter is this id; absent means all of them. */
  id?: string
}

/** A resource read through the cache: `cached('getExecution', [id], (s) => request(path, { signal: s }), { signal, staleAfter: 'detail' })`. */
export function cached<T>(name: ResourceName, params: readonly unknown[], fetcher: (signal: AbortSignal) => Promise<T>, options: QueryGetOptions): Promise<T> {
  return queryCache.get(name, params, fetcher, options)
}

/** Mark every entry the targets address stale. Returns how many matched. */
export function invalidateTargets(targets: readonly QueryTarget[], cache: QueryCache = queryCache): number {
  if (targets.length === 0) return 0
  return cache.invalidate((e) => targets.some((t) => t.name === e.name && (t.id === undefined || e.params[0] === t.id)))
}

/** Invalidate after a mutation settles, whichever way it went. */
export async function thenInvalidate<T>(mutation: Promise<T>, targets: readonly QueryTarget[]): Promise<T> {
  try {
    return await mutation
  } finally {
    invalidateTargets(targets)
  }
}
