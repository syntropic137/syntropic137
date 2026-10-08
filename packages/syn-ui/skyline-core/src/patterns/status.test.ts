import { describe, expect, it } from 'vitest'
import { humanize, statusKind, statusSemantics } from './index'
import { statusToken, type StatusKind } from './status'

describe('statusSemantics', () => {
  it('maps the spec trio once', () => {
    expect(statusSemantics('completed')).toMatchObject({ variant: 'soft', tone: 'success', label: 'Completed' })
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
  it('gives every state its own token, glyph and label (owner tweak after demo)', () => {
    const kinds: StatusKind[] = ['completed', 'failed', 'running', 'pending', 'cancelled', 'interrupted']
    const all = kinds.map((k) => statusSemantics(k))
    expect(new Set(all.map((s) => s.token)).size).toBe(kinds.length)
    expect(new Set(all.map((s) => s.glyph)).size).toBe(kinds.length)
    expect(statusSemantics('completed')).toMatchObject({ token: 'var(--sky-status-completed)', glyph: 'check' })
    expect(statusSemantics('failed')).toMatchObject({ token: 'var(--sky-status-failed)', glyph: 'cross' })
    expect(statusSemantics('in_progress')).toMatchObject({ token: 'var(--sky-status-running)', glyph: 'spinner', live: true })
    expect(statusSemantics('queued')).toMatchObject({ token: 'var(--sky-status-pending)', glyph: 'clock', live: false })
    expect(statusSemantics('interrupted').tone).toBe('warning')
    expect(statusToken('skipped')).toBe('var(--sky-status-skipped)')
    expect(statusSemantics('nope').token).toBe('var(--sky-status-unknown)')
  })
})
