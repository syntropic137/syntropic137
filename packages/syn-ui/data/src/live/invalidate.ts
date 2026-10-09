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
  const executionId = str(frame.execution_id) ?? str(data.execution_id)
  const workflowId = str(data.workflow_id)
  const sessionId = str(data.session_id)
  const out: QueryTarget[] = [{ name: 'getMetrics' }]
  if (isRunEvent(t)) {
    out.push(
      { name: 'listExecutions' },
      { name: 'getExecutionBudget' },
      { name: 'listWorkflowRuns', id: workflowId },
      { name: 'getWorkflowHistory', id: workflowId },
      { name: 'getWorkflowTrend', id: workflowId },
      { name: 'listExecutionCosts' },
      { name: 'getCostSummary' },
    )
    if (executionId) out.push({ name: 'getExecution', id: executionId }, { name: 'getExecutionCost', id: executionId })
  }
  if (t === 'WorkflowExecutionStarted' || isRunFinished(t)) {
    out.push({ name: 'listWorkflows' }, { name: 'getWorkflow', id: workflowId }, { name: 'getContributionHeatmap' })
  }
  if (isRunFinished(t)) out.push({ name: 'listEvals' }, { name: 'getEval' }, { name: 'listEvalRuns' }, { name: 'getEvalTrend' })
  if (isSessionEvent(t)) {
    out.push(
      { name: 'listSessions' },
      { name: 'getSession', id: sessionId },
      { name: 'getToolTimeline', id: sessionId },
      { name: 'getTokenMetrics', id: sessionId },
      { name: 'getConversationLog', id: sessionId },
    )
  }
  if (t === 'SessionStarted' || t === 'SessionCompleted') {
    out.push({ name: 'listSessionCosts' }, { name: 'getSessionCost', id: sessionId }, { name: 'getCostSummary' }, { name: 'getContributionHeatmap' })
    if (executionId) out.push({ name: 'getExecution', id: executionId }, { name: 'getSessionInventory', id: executionId })
  }
  if (isArtifactEvent(t)) out.push({ name: 'listArtifacts' }, { name: 'getArtifact', id: str(data.artifact_id) })
  if (isGitEvent(t)) out.push({ name: 'getContributionHeatmap' })
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
