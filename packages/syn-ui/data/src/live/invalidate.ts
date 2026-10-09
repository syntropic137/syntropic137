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
import { subscribeActivity } from './stream'

const str = (v: unknown): string | undefined => (typeof v === 'string' && v ? v : undefined)

const isExecution = (t: string) => t.startsWith('phase_') || t.startsWith('workflow_') || t.startsWith('execution_')
const isSession = (t: string) => t.startsWith('session') || t.startsWith('tool_') || t.startsWith('subagent_')

/** The cached reads one live frame makes stale. Metrics go stale on every event. */
export function invalidationsFor(frame: SSEEventFrame): QueryTarget[] {
  if (frame.type !== 'event') return []
  const t = frame.event_type
  const data = frame.data ?? {}
  const executionId = str(frame.execution_id) ?? str(data.execution_id)
  const out: QueryTarget[] = [{ name: 'getMetrics' }]
  if (isExecution(t)) {
    const workflowId = str(data.workflow_id)
    out.push(
      { name: 'listExecutions' },
      { name: 'getExecutionBudget' },
      { name: 'listWorkflowRuns', id: workflowId },
      { name: 'listExecutionCosts' },
      { name: 'getCostSummary' },
    )
    if (executionId) out.push({ name: 'getExecution', id: executionId }, { name: 'getExecutionCost', id: executionId })
  }
  if (isSession(t)) {
    const sessionId = str(data.session_id)
    out.push(
      { name: 'listSessions' },
      { name: 'getSession', id: sessionId },
      { name: 'getToolTimeline', id: sessionId },
      { name: 'getTokenMetrics', id: sessionId },
    )
  }
  if (t.startsWith('artifact_')) out.push({ name: 'listArtifacts' }, { name: 'getArtifact', id: str(data.artifact_id) })
  if (t.startsWith('trigger')) {
    const triggerId = str(data.trigger_id)
    out.push({ name: 'listTriggers' }, { name: 'getTrigger', id: triggerId }, { name: 'getTriggerHistory', id: triggerId })
  }
  // An absent id means "all of that resource": strip it so the target is unambiguous.
  return out.map((target) => (target.id === undefined ? { name: target.name } : target))
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
  return () => {
    clearTimeout(timer)
    unsubscribe()
  }
}
