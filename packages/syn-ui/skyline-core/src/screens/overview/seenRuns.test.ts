import { describe, expect, it } from 'vitest'
import { markSeen, parseSeenRuns, seenSignature, seenToggleLabel, splitSeenRuns } from './seenRuns'

const run = (id: string, completed: string | null, status = 'failed') => ({ workflow_execution_id: id, workflow_name: id, status, started_at: '2026-10-09T10:00:00Z', completed_at: completed })

describe('seen runs (feedback 443e9c0a)', () => {
  it('signs a run by id and the failure it ended in', () => {
    expect(seenSignature(run('a', '2026-10-09T11:00:00Z'))).toBe('a@2026-10-09T11:00:00Z')
    expect(seenSignature(run('a', null))).toBe('a@2026-10-09T10:00:00Z')
  })
  it('hides seen runs and keeps order', () => {
    const runs = [run('a', 't1'), run('b', 't2'), run('c', 't3')]
    const s = splitSeenRuns(runs, ['b@t2'])
    expect(s.fresh.map((r) => r.workflow_execution_id)).toEqual(['a', 'c'])
    expect(s.seen.map((r) => r.workflow_execution_id)).toEqual(['b'])
  })
  it('brings a run back when it fails again later', () => {
    expect(splitSeenRuns([run('a', 't9')], ['a@t1']).fresh).toHaveLength(1)
  })
  it('remembers newest last, deduped and capped', () => {
    expect(markSeen(['x', 'y'], 'x')).toEqual(['y', 'x'])
    expect(markSeen(['1', '2', '3'], '4', 3)).toEqual(['2', '3', '4'])
  })
  it('reads storage defensively', () => {
    expect(parseSeenRuns('["a@t",1,null]')).toEqual(['a@t'])
    expect(parseSeenRuns('{')).toEqual([])
    expect(parseSeenRuns('{"a":1}')).toEqual([])
    expect(parseSeenRuns(null)).toEqual([])
  })
  it('labels the toggle', () => {
    expect(seenToggleLabel(2, false)).toBe('2 seen · show')
    expect(seenToggleLabel(1, true)).toBe('1 seen · hide')
  })
})
