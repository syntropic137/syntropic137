import { describe, expect, it } from 'vitest'
import { humanize, statusKind, statusSemantics } from './index'

describe('statusSemantics', () => {
  it('maps the spec trio once', () => {
    expect(statusSemantics('completed')).toMatchObject({ variant: 'soft', tone: 'accent', label: 'Completed' })
    expect(statusSemantics('failed')).toMatchObject({ variant: 'soft', tone: 'danger', label: 'Failed' })
    expect(statusSemantics('cancelled')).toMatchObject({ variant: 'outline', tone: 'neutral' })
  })
  it('treats aliases and live states', () => {
    expect(statusKind('in_progress')).toBe('running')
    expect(statusSemantics('RUNNING').live).toBe(true)
    expect(statusSemantics('queued')).toMatchObject({ kind: 'pending', label: 'Queued' })
    expect(statusSemantics('not_started').label).toBe('Pending')
  })
  it('keeps unknown statuses readable', () => {
    expect(statusSemantics('waiting_for_review')).toMatchObject({ kind: 'unknown', label: 'Waiting for review' })
    expect(statusSemantics(null).label).toBe('Unknown')
    expect(humanize('not_started')).toBe('Not started')
  })
})
