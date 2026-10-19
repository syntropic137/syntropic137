import { describe, expect, it } from 'vitest'
import { artifactGlyph, artifactName, baseName, groupArtifactsByRun, groupFileCount } from './index'

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

describe('run groups count the run, not the page (parity-2 #4: "43 files" vs API total 75)', () => {
  const rows = [
    { id: 'a', workflow_id: 'sdlc', execution_id: 'exec-64e1d7e33b6a', created_at: '2026-10-09T23:00:00Z' },
    { id: 'b', workflow_id: 'sdlc', execution_id: 'exec-64e1d7e33b6a', created_at: '2026-10-09T22:00:00Z' },
    { id: 'c', workflow_id: 'research', execution_id: null, created_at: null },
  ]
  it('groups by run in page order', () => {
    const groups = groupArtifactsByRun(rows)
    expect(groups.map((g) => [g.key, g.files.length])).toEqual([['exec-64e1d7e33b6a', 2], ['research', 1]])
    expect(groups[1]!.exec).toBeNull()
  })
  it("uses the API's total for the run", () => {
    expect(groupFileCount(43, 75)).toBe('75 files · 43 on this page')
    expect(groupFileCount(8, 8)).toBe('8 files')
    expect(groupFileCount(1, 1)).toBe('1 file')
    expect(groupFileCount(43, undefined)).toBe('43 on this page')
  })
})
