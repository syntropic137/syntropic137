import { describe, expect, it } from 'vitest'
import { artifactGlyph, artifactName, baseName } from './index'

describe('artifactName', () => {
  it('splits a phase label from a path in the title', () => {
    expect(artifactName('Open the pull request: artifacts/output/pr-body.md')).toEqual({
      name: 'pr-body.md',
      label: 'Open the pull request',
      path: 'artifacts/output/pr-body.md',
    })
  })
  it('keeps a plain title as the name', () => {
    expect(artifactName('Review output')).toEqual({ name: 'Review output', label: null, path: null })
  })
  it('prefers metadata.path and keeps the title as the label', () => {
    expect(artifactName('Synthesis & Documentation', 'artifacts/output/deliverable.md')).toEqual({
      name: 'deliverable.md',
      label: 'Synthesis & Documentation',
      path: 'artifacts/output/deliverable.md',
    })
  })
  it('does not treat a colon sentence without a path as one', () => {
    expect(artifactName('Note: read this').path).toBeNull()
  })
  it('falls back when there is no title', () => {
    expect(artifactName(null, null, 'abc123').name).toBe('abc123')
  })
})

describe('baseName and artifactGlyph', () => {
  it('takes the last segment', () => {
    expect(baseName('a/b/c.md')).toBe('c.md')
    expect(baseName('c.md')).toBe('c.md')
  })
  it('picks a glyph family', () => {
    expect(artifactGlyph('code')).toBe('code')
    expect(artifactGlyph('markdown', 'x/palindrome.py')).toBe('code')
    expect(artifactGlyph('json')).toBe('data')
    expect(artifactGlyph('research_summary')).toBe('doc')
  })
})
