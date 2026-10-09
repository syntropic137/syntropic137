import { describe, expect, it, vi } from 'vitest'
import type { QueryTarget } from '../keys'
import type { SSEEventFrame } from '../types'
// The API source that names every live event (read-only; see events.ts).
import realtimePy from '../../../../syn-adapters/src/syn_adapters/projections/realtime.py?raw'
import pushEventsPy from '../../../../../apps/syn-api/src/syn_api/routes/webhooks/push_events.py?raw'
import { ACTIVITY_EVENT_TYPES, EXECUTION_STREAM_EVENT_TYPES, LIVE_EVENT_TYPES } from './events'
import { connectLiveInvalidation, invalidationsFor, mergeTargets } from './invalidate'

const frame = (event_type: string, data: Record<string, unknown> = {}, execution_id: string | null = null): SSEEventFrame => ({
  type: 'event',
  event_type,
  execution_id,
  data,
  timestamp: '2026-10-08T00:00:00Z',
})
const names = (targets: QueryTarget[]) => targets.map((t) => (t.id ? `${t.name}:${t.id}` : t.name)).sort()

describe('invalidationsFor (real API event names)', () => {
  it('run events: executions, that detail, its workflow runs, history and trend, budget, costs, metrics', () => {
    expect(names(invalidationsFor(frame('PhaseCompleted', { workflow_id: 'wf' }, 'ex')))).toEqual(
      [
        'getMetrics',
        'listExecutions',
        'getExecutionBudget',
        'listWorkflowRuns:wf',
        'getWorkflowHistory:wf',
        'getWorkflowTrend:wf',
        'listExecutionCosts',
        'getCostSummary',
        'getExecution:ex',
        'getExecutionCost:ex',
      ].sort(),
    )
  })
  it('a finished run also refreshes its workflow, evals and the heatmap', () => {
    // Activity frames carry execution_id in data (the frame's own is null on that channel).
    const got = names(invalidationsFor(frame('WorkflowCompleted', { workflow_id: 'wf', execution_id: 'ex' })))
    for (const n of ['getExecution:ex', 'getWorkflowHistory:wf', 'getWorkflowTrend:wf', 'listWorkflows', 'getWorkflow:wf', 'listEvalRuns', 'getEvalTrend', 'getContributionHeatmap']) {
      expect(got).toContain(n)
    }
  })
  it('a run event with no workflow id refreshes every workflow run list', () => {
    expect(invalidationsFor(frame('WorkflowFailed', {}, 'ex'))).toContainEqual({ name: 'listWorkflowRuns' })
  })
  it('session events refresh sessions, session costs, the cost summary and the heatmap', () => {
    expect(names(invalidationsFor(frame('SessionCompleted', { session_id: 's', execution_id: 'ex' })))).toEqual(
      [
        'getMetrics',
        'listSessions',
        'getSession:s',
        'getToolTimeline:s',
        'getTokenMetrics:s',
        'getConversationLog:s',
        'listSessionCosts',
        'getSessionCost:s',
        'getCostSummary',
        'getContributionHeatmap',
        'getExecution:ex',
        'getSessionInventory:ex',
      ].sort(),
    )
  })
  it('artifact and git events refresh their resources', () => {
    expect(names(invalidationsFor(frame('ArtifactCreated', { artifact_id: 'a' })))).toEqual(['getArtifact:a', 'getMetrics', 'listArtifacts'])
    expect(names(invalidationsFor(frame('git_commit')))).toEqual(['getContributionHeatmap', 'getMetrics'])
  })
  it('terminal frames map like events; nothing for handshakes', () => {
    expect(names(invalidationsFor({ ...frame('WorkflowCompleted', {}, 'ex'), type: 'terminal' }))).toContain('getExecution:ex')
    expect(invalidationsFor({ ...frame('connected'), type: 'connected' })).toEqual([])
  })
})

describe('contract: every event the API emits invalidates something', () => {
  // Read the Python that names them, so a new event type fails here until events.ts and the map know it.
  const emitted = (source: string, pattern: RegExp) => [...source.matchAll(pattern)].map((m) => m[1]!)
  const realtime = realtimePy

  it('events.ts lists exactly the names the API source emits', () => {
    const activity = new Set([
      ...emitted(realtime, /broadcast_global\("([^"]+)"/g),
      ...emitted(pushEventsPy, /broadcast_global\("([^"]+)"/g),
    ])
    const perExecution = new Set(emitted(realtime, /_forward_event\([^,]+,\s*"([^"]+)"/g))
    expect([...activity].sort()).toEqual([...ACTIVITY_EVENT_TYPES].sort())
    expect([...perExecution].filter((t) => !activity.has(t)).sort()).toEqual([...EXECUTION_STREAM_EVENT_TYPES].sort())
  })

  it.each([...LIVE_EVENT_TYPES])('%s invalidates more than metrics', (t) => {
    const targets = invalidationsFor(frame(t, { execution_id: 'ex', workflow_id: 'wf', session_id: 's', artifact_id: 'a' }))
    expect(targets.filter((x) => x.name !== 'getMetrics').length).toBeGreaterThan(0)
  })
})

describe('mergeTargets', () => {
  it('dedupes and lets a whole-resource target absorb id targets', () => {
    expect(mergeTargets([{ name: 'getSession', id: 'a' }, { name: 'getSession' }, { name: 'getSession', id: 'b' }, { name: 'getMetrics' }, { name: 'getMetrics' }])).toEqual([
      { name: 'getSession' },
      { name: 'getMetrics' },
    ])
  })
})

describe('connectLiveInvalidation', () => {
  it('applies a burst once, then throttles to the interval', () => {
    vi.useFakeTimers()
    let deliver: (frames: SSEEventFrame[]) => void = () => {}
    const off = vi.fn()
    const apply = vi.fn()
    const stop = connectLiveInvalidation({ minIntervalMs: 1000, apply, subscribe: (fn) => ((deliver = fn), off) })
    deliver([frame('git_commit'), frame('git_commit')])
    expect(apply).toHaveBeenCalledExactlyOnceWith([{ name: 'getMetrics' }, { name: 'getContributionHeatmap' }])
    deliver([frame('ArtifactCreated')])
    expect(apply).toHaveBeenCalledTimes(1)
    vi.advanceTimersByTime(1000)
    expect(apply).toHaveBeenCalledTimes(2)
    expect(names(apply.mock.calls[1]![0])).toEqual(['getArtifact', 'getMetrics', 'listArtifacts'])
    stop()
    expect(off).toHaveBeenCalled()
    vi.useRealTimers()
  })
})

describe('connectLiveInvalidation teardown', () => {
  it('flushes targets the throttle was holding', () => {
    vi.useFakeTimers()
    try {
      let deliver: (frames: SSEEventFrame[]) => void = () => {}
      const apply = vi.fn()
      const stop = connectLiveInvalidation({ minIntervalMs: 1000, apply, subscribe: (fn) => ((deliver = fn), () => {}) })
      deliver([frame('git_commit')])
      deliver([frame('ArtifactCreated', { artifact_id: 'a' })]) // inside the interval: queued
      expect(apply).toHaveBeenCalledTimes(1)
      stop()
      expect(apply).toHaveBeenCalledTimes(2)
      expect(names(apply.mock.calls[1]![0])).toContain('listArtifacts')
      vi.advanceTimersByTime(5000)
      expect(apply).toHaveBeenCalledTimes(2)
    } finally {
      vi.useRealTimers()
    }
  })
})
