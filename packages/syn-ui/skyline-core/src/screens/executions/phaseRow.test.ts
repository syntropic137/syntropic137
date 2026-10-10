import { describe, expect, it } from 'vitest'
import { phaseRowTarget } from './index'

describe('phaseRowTarget (feedback 1f70d3ab)', () => {
  it('a phase with a session opens that session', () => {
    expect(phaseRowTarget({ name: 'Verify', status: 'completed', session_id: '913f8676-fd9f' })).toEqual({
      kind: 'session',
      path: '/sessions/913f8676-fd9f',
      label: 'Open the session for Verify',
    })
  })

  it('a running phase with its session already recorded is a link too', () => {
    expect(phaseRowTarget({ name: 'Implement', status: 'running', session_id: 's-1' }).kind).toBe('session')
  })

  it('encodes the session id into the path', () => {
    const t = phaseRowTarget({ name: 'x', status: 'completed', session_id: 'a/b c' })
    expect(t.kind === 'session' && t.path).toBe('/sessions/a%2Fb%20c')
  })

  it('a planned phase is not a link and says it has not started', () => {
    const t = phaseRowTarget({ name: 'Fix', status: 'pending' }, true)
    expect(t).toEqual({ kind: 'none', reason: 'This phase has not started yet, so it has no session to open.' })
  })

  it('a running phase without a session yet says it is not recorded yet', () => {
    const t = phaseRowTarget({ name: 'Fix', status: 'running', session_id: null })
    expect(t.kind === 'none' && t.reason).toBe('The session for this phase has not been recorded yet.')
  })

  it('a finished phase that never recorded a session says so', () => {
    const t = phaseRowTarget({ name: 'Fix', status: 'failed', session_id: '' })
    expect(t.kind === 'none' && t.reason).toBe('No session was recorded for this phase.')
  })
})
