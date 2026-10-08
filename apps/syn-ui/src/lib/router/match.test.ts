import { describe, expect, it } from 'vitest'
import { compilePattern, matchPattern, stripBase, withBase } from './match'

describe('route matching', () => {
  it('matches the root only at the root', () => {
    const root = compilePattern('/')
    expect(matchPattern(root, '/')).toEqual({})
    expect(matchPattern(root, '/executions')).toBeNull()
  })
  it('extracts and decodes params, tolerates a trailing slash', () => {
    const p = compilePattern('/workflows/:workflowId/runs')
    expect(matchPattern(p, '/workflows/research%20flow/runs/')).toEqual({ workflowId: 'research flow' })
    expect(matchPattern(p, '/workflows/x')).toBeNull()
  })
  it('supports a wildcard tail', () => {
    const p = compilePattern('/insights/*')
    expect(matchPattern(p, '/insights')).toEqual({})
    expect(matchPattern(p, '/insights/cost/by-model')).toEqual({})
  })
  it('strips and adds the deploy base', () => {
    expect(stripBase('/next/executions', '/next/')).toBe('/executions')
    expect(stripBase('/next', '/next/')).toBe('/')
    expect(stripBase('/nextgen', '/next/')).toBe('/nextgen')
    expect(stripBase('/executions', '/')).toBe('/executions')
    expect(withBase('/executions', '/next/')).toBe('/next/executions')
    expect(withBase('/', '/')).toBe('/')
  })
})
