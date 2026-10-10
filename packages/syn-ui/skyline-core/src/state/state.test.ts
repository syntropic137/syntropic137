import { describe, expect, it } from 'vitest'
import { copyFeedback, run } from './index'

describe('copyFeedback', () => {
  it('goes idle -> copying -> copied -> idle', () => {
    expect(run(copyFeedback, 'idle', [{ type: 'copy' }, { type: 'success' }])).toBe('copied')
    expect(run(copyFeedback, 'copied', [{ type: 'reset' }])).toBe('idle')
  })
  it('records failure and ignores stray results', () => {
    expect(run(copyFeedback, 'idle', [{ type: 'copy' }, { type: 'error' }])).toBe('failed')
    expect(run(copyFeedback, 'idle', [{ type: 'success' }])).toBe('idle')
  })
})
