import { describe, expect, it, vi } from 'vitest'
import type { QueryTarget } from '../keys'
import type { SSEEventFrame } from '../types'
import { connectLiveInvalidation, invalidationsFor, mergeTargets } from './invalidate'

const frame = (event_type: string, data: Record<string, unknown> = {}, execution_id: string | null = null): SSEEventFrame => ({
  type: 'event',
  event_type,
  execution_id,
  data,
  timestamp: '2026-10-08T00:00:00Z',
})
const names = (targets: QueryTarget[]) => targets.map((t) => (t.id ? `${t.name}:${t.id}` : t.name)).sort()

describe('invalidationsFor', () => {
  it('execution events: list, that detail, its workflow runs, budget, costs, metrics', () => {
    expect(names(invalidationsFor(frame('phase_completed', { workflow_id: 'wf' }, 'ex')))).toEqual(
      [
        'getMetrics',
        'listExecutions',
        'getExecutionBudget',
        'listWorkflowRuns:wf',
        'listExecutionCosts',
        'getCostSummary',
        'getExecution:ex',
        'getExecutionCost:ex',
      ].sort(),
    )
  })
  it('an execution event with no workflow id refreshes every workflow run list', () => {
    expect(invalidationsFor(frame('workflow_failed', {}, 'ex'))).toContainEqual({ name: 'listWorkflowRuns' })
  })
  it('session, tool and subagent events refresh sessions', () => {
    for (const t of ['session_started', 'tool_execution_completed', 'subagent_stopped']) {
      expect(names(invalidationsFor(frame(t, { session_id: 's' })))).toEqual(
        ['getMetrics', 'listSessions', 'getSession:s', 'getToolTimeline:s', 'getTokenMetrics:s'].sort(),
      )
    }
  })
  it('artifact and trigger events refresh their resources', () => {
    expect(names(invalidationsFor(frame('artifact_created', { artifact_id: 'a' })))).toEqual(['getArtifact:a', 'getMetrics', 'listArtifacts'])
    expect(names(invalidationsFor(frame('trigger_fired', { trigger_id: 't' })))).toEqual(
      ['getMetrics', 'getTrigger:t', 'getTriggerHistory:t', 'listTriggers'],
    )
  })
  it('metrics on any event; nothing for handshakes', () => {
    expect(invalidationsFor(frame('git_commit'))).toEqual([{ name: 'getMetrics' }])
    expect(invalidationsFor({ ...frame('connected'), type: 'connected' })).toEqual([])
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
    deliver([frame('git_commit'), frame('git_push')])
    expect(apply).toHaveBeenCalledExactlyOnceWith([{ name: 'getMetrics' }])
    deliver([frame('artifact_created')])
    expect(apply).toHaveBeenCalledTimes(1)
    vi.advanceTimersByTime(1000)
    expect(apply).toHaveBeenCalledTimes(2)
    expect(names(apply.mock.calls[1]![0])).toEqual(['getArtifact', 'getMetrics', 'listArtifacts'])
    stop()
    expect(off).toHaveBeenCalled()
    vi.useRealTimers()
  })
})
