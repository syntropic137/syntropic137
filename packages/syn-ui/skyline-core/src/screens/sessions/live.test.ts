import { describe, expect, it } from 'vitest'
import { LIVE_OPS_INITIAL, RUNNING_SESSION_POLL_MS, liveOps, newestFirst, sessionOperations, sessionPollMs, unseenLabel, type SessionOperationInput } from './index'

const op = (id: string, ts: string, tool = 'Bash'): SessionOperationInput => ({
  operation_id: id,
  operation_type: 'tool_execution_completed',
  timestamp: ts,
  success: true,
  tool_name: tool,
  tool_use_id: id,
  tool_input: { command: id },
})

describe('newestFirst (feedback 18ec6964)', () => {
  it('puts the latest operation at the top and the earliest at the bottom', () => {
    const rows = sessionOperations([op('b', '2026-10-10T00:00:02Z'), op('c', '2026-10-10T00:00:03Z'), op('a', '2026-10-10T00:00:01Z')])
    expect(newestFirst(rows).map((r) => r.input)).toEqual(['c', 'b', 'a'])
  })

  it('does not mutate its input', () => {
    const rows = [1, 2, 3]
    newestFirst(rows)
    expect(rows).toEqual([1, 2, 3])
  })
})

describe('liveOps reducer', () => {
  const load = (ids: string[], atTop = true) => liveOps(LIVE_OPS_INITIAL, { type: 'rows', ids, atTop })

  it('treats the first load as the baseline: nothing is new', () => {
    const s = load(['a', 'b'], false)
    expect(s.added).toBe(0)
    expect(s.unseen).toBe(0)
    expect([...(s.known ?? [])]).toEqual(['a', 'b'])
  })

  it('counts rows that arrive while the reader is at the top as added but not unseen', () => {
    const s = liveOps(load(['a']), { type: 'rows', ids: ['c', 'b', 'a'], atTop: true })
    expect(s.added).toBe(2)
    expect(s.unseen).toBe(0)
  })

  it('accumulates unseen rows while the reader is scrolled down', () => {
    let s = liveOps(load(['a']), { type: 'rows', ids: ['b', 'a'], atTop: false })
    expect(s).toMatchObject({ added: 1, unseen: 1 })
    s = liveOps(s, { type: 'rows', ids: ['d', 'c', 'b', 'a'], atTop: false })
    expect(s).toMatchObject({ added: 2, unseen: 3 })
  })

  it('a refetch with the same rows (a running row updated in place) adds nothing', () => {
    const before = liveOps(load(['a']), { type: 'rows', ids: ['b', 'a'], atTop: false })
    const after = liveOps(before, { type: 'rows', ids: ['b', 'a'], atTop: false })
    expect(after).toMatchObject({ added: 0, unseen: 1 })
  })

  it('returns the same state when nothing changed, so the screen does not re-render', () => {
    const s = load(['a'])
    expect(liveOps(s, { type: 'rows', ids: ['a'], atTop: true })).toBe(s)
    expect(liveOps(s, { type: 'seen' })).toBe(s)
  })

  it('reaching the top clears the unseen count', () => {
    const s = liveOps(liveOps(load(['a']), { type: 'rows', ids: ['b', 'a'], atTop: false }), { type: 'seen' })
    expect(s).toMatchObject({ added: 0, unseen: 0 })
  })

  it('a filter that hides rows and shows them again does not count them as new', () => {
    let s = load(['b', 'a'])
    s = liveOps(s, { type: 'rows', ids: ['a'], atTop: false })
    s = liveOps(s, { type: 'rows', ids: ['b', 'a'], atTop: false })
    expect(s).toMatchObject({ added: 0, unseen: 0 })
  })
})

describe('unseenLabel and sessionPollMs', () => {
  it('reads naturally', () => {
    expect(unseenLabel(1)).toBe('1 new operation')
    expect(unseenLabel(4)).toBe('4 new operations')
  })

  it('polls only while the session runs', () => {
    expect(sessionPollMs('running')).toBe(RUNNING_SESSION_POLL_MS)
    expect(sessionPollMs('started')).toBe(RUNNING_SESSION_POLL_MS)
    expect(sessionPollMs('completed')).toBeNull()
    expect(sessionPollMs('failed')).toBeNull()
    expect(sessionPollMs(null)).toBeNull()
  })
})
