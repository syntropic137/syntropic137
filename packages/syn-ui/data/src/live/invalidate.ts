/**
 * Live events -> query cache invalidations (ADR-074).
 *
 * `invalidationsFor` is the pure mapping: which cached reads one activity
 * frame makes stale. `connectLiveInvalidation` subscribes to the activity
 * stream and applies it, batching a burst into one invalidation pass at
 * most every `minIntervalMs`, so a chatty stream cannot refetch a screen
 * once per event.
 */
import type { QueryTarget } from '../keys'
import { invalidateTargets } from '../keys'
import type { SSEEventFrame } from '../types'
import { isArtifactEvent, isGitEvent, isRunEvent, isRunFinished, isSessionEvent } from './events'
import { subscribeActivity } from './stream'

const str = (v: unknown): string | undefined => (typeof v === 'string' && v ? v : undefined)

interface FrameIds {
  executionId?: string
  workflowId?: string
  sessionId?: string
  artifactId?: string
}

const isRunEdge = (t: string) => t === 'WorkflowExecutionStarted' || isRunFinished(t)
const isSessionEdge = (t: string) => t === 'SessionStarted' || t === 'SessionCompleted'
const when = (ok: boolean, targets: QueryTarget[]): QueryTarget[] => (ok ? targets : [])

/** Event predicate -> the reads it stales. Order is irrelevant: targets are merged. */
const RULES: ReadonlyArray<readonly [(t: string) => boolean, (ids: FrameIds) => QueryTarget[]]> = [
  [
    isRunEvent,
    ({ executionId, workflowId }) => [
      { name: 'listExecutions' },
      { name: 'getExecutionBudget' },
      { name: 'listWorkflowRuns', id: workflowId },
      { name: 'getWorkflowHistory', id: workflowId },
      { name: 'getWorkflowTrend', id: workflowId },
      { name: 'listExecutionCosts' },
      { name: 'getCostSummary' },
      ...when(!!executionId, [{ name: 'getExecution', id: executionId }, { name: 'getExecutionCost', id: executionId }]),
    ],
  ],
  [isRunEdge, ({ workflowId }) => [{ name: 'listWorkflows' }, { name: 'getWorkflow', id: workflowId }, { name: 'getContributionHeatmap' }]],
  [isRunFinished, () => [{ name: 'listEvals' }, { name: 'getEval' }, { name: 'listEvalRuns' }, { name: 'getEvalTrend' }]],
  [
    isSessionEvent,
    ({ sessionId }) => [
      { name: 'listSessions' },
      { name: 'getSession', id: sessionId },
      { name: 'getToolTimeline', id: sessionId },
      { name: 'getTokenMetrics', id: sessionId },
      { name: 'getConversationLog', id: sessionId },
    ],
  ],
  [
    isSessionEdge,
    ({ sessionId, executionId }) => [
      { name: 'listSessionCosts' },
      { name: 'getSessionCost', id: sessionId },
      { name: 'getCostSummary' },
      { name: 'getContributionHeatmap' },
      ...when(!!executionId, [{ name: 'getExecution', id: executionId }, { name: 'getSessionInventory', id: executionId }]),
    ],
  ],
  [isArtifactEvent, ({ artifactId }) => [{ name: 'listArtifacts' }, { name: 'getArtifact', id: artifactId }]],
  [isGitEvent, () => [{ name: 'getContributionHeatmap' }]],
]

/**
 * The cached reads one live frame makes stale, keyed by the API's real
 * `event_type` names (events.ts lists them; a contract test pins that every
 * one maps here). Metrics go stale on every event; an unknown name stales
 * metrics only.
 */
export function invalidationsFor(frame: SSEEventFrame): QueryTarget[] {
  if (frame.type === 'connected') return []
  const t = frame.event_type
  const data = frame.data ?? {}
  const ids: FrameIds = {
    executionId: str(frame.execution_id) ?? str(data.execution_id),
    workflowId: str(data.workflow_id),
    sessionId: str(data.session_id),
    artifactId: str(data.artifact_id),
  }
  const out: QueryTarget[] = [{ name: 'getMetrics' }]
  for (const [applies, targets] of RULES) if (applies(t)) out.push(...targets(ids))
  // An absent id means "all of that resource": strip it so the target is unambiguous.
  return mergeTargets(out.map((target) => (target.id === undefined ? { name: target.name } : target)))
}

/** Union of targets, a whole-resource target absorbing that resource's id targets. */
export function mergeTargets(targets: readonly QueryTarget[]): QueryTarget[] {
  const whole = new Set(targets.filter((t) => t.id === undefined).map((t) => t.name))
  const seen = new Set<string>()
  return targets.filter((t) => {
    if (t.id !== undefined && whole.has(t.name)) return false
    const key = `${t.name}\u0000${t.id ?? ''}`
    if (seen.has(key)) return false
    seen.add(key)
    return true
  })
}

export interface LiveInvalidationOptions {
  /** Minimum gap between invalidation passes, ms (default 1000). */
  minIntervalMs?: number
  /** Injectable for tests; defaults to the activity stream. */
  subscribe?: (onFrames: (frames: SSEEventFrame[]) => void) => () => void
  apply?: (targets: QueryTarget[]) => void
}

/** Keep the cache in step with the activity stream. Returns the stop function. */
export function connectLiveInvalidation(options: LiveInvalidationOptions = {}): () => void {
  const gap = options.minIntervalMs ?? 1000
  const apply = options.apply ?? ((targets: QueryTarget[]) => void invalidateTargets(targets))
  let pending: QueryTarget[] = []
  let last = 0
  let timer: ReturnType<typeof setTimeout> | undefined
  const flush = () => {
    timer = undefined
    last = Date.now()
    const targets = mergeTargets(pending)
    pending = []
    if (targets.length) apply(targets)
  }
  const onFrames = (frames: SSEEventFrame[]) => {
    for (const f of frames) pending.push(...invalidationsFor(f))
    if (timer || pending.length === 0) return
    const wait = last + gap - Date.now()
    if (wait <= 0) flush()
    else timer = setTimeout(flush, wait)
  }
  const unsubscribe = options.subscribe?.(onFrames) ?? subscribeActivity({ onFrames })
  // Teardown flushes what the throttle was holding, so a queued invalidation is never lost.
  return () => {
    unsubscribe()
    clearTimeout(timer)
    if (pending.length) flush()
  }
}
