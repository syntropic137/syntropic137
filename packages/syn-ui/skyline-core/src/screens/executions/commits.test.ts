import { describe, expect, it } from 'vitest'
import { COMMITS_NOT_RECORDED, commitsView, phaseCommitsView } from './detail'

const SHA = '4f2a9c1e88d07b3a5c6d7e8f9a0b1c2d3e4f5a6b'
const OTHER = '9b8a7c6d5e4f3a2b1c0d9e8f7a6b5c4d3e2f1a0b'

describe('commitsView (#1004)', () => {
  it('says a run from before capture did not record a commit, never an empty list', () => {
    expect(commitsView(null)).toEqual({ kind: 'absent', text: COMMITS_NOT_RECORDED })
    expect(commitsView(undefined)).toEqual({ kind: 'absent', text: COMMITS_NOT_RECORDED })
  })

  it('says a run that checked nothing out in words', () => {
    expect(commitsView([])).toEqual({ kind: 'absent', text: 'no repository checked out' })
  })

  it('shows the 7-character SHA and keeps the full one to copy', () => {
    expect(commitsView([{ repository: 'acme/api', sha: SHA }])).toEqual({
      kind: 'commits',
      lines: [{ repository: 'acme/api', short: '4f2a9c1', sha: SHA, text: 'acme/api @ 4f2a9c1' }],
    })
  })

  it('says a recorded but unresolved commit is unresolved, never a blank', () => {
    const view = commitsView([{ repository: 'acme/web', sha: null }, { repository: 'acme/cli' }])
    expect(view).toEqual({
      kind: 'commits',
      lines: [
        { repository: 'acme/web', short: null, sha: null, text: 'acme/web @ unresolved' },
        { repository: 'acme/cli', short: null, sha: null, text: 'acme/cli @ unresolved' },
      ],
    })
  })
})

describe('phaseCommitsView (#1004)', () => {
  const run = [
    { repository: 'acme/api', sha: SHA },
    { repository: 'acme/web', sha: null },
  ]

  it('says nothing for a phase checked out where the run was, in any order', () => {
    expect(phaseCommitsView([...run].reverse(), run)).toBeNull()
  })

  it('shows a phase checked out at a different commit', () => {
    const view = phaseCommitsView([{ repository: 'acme/api', sha: OTHER }, run[1]!], run)
    expect(view?.kind === 'commits' && view.lines.map((l) => l.text)).toEqual(['acme/api @ 9b8a7c6', 'acme/web @ unresolved'])
  })

  it('shows a phase whose unresolved commit resolved', () => {
    expect(phaseCommitsView([run[0]!, { repository: 'acme/web', sha: OTHER }], run)).not.toBeNull()
  })

  it('says nothing for a phase that recorded no commits: the run line already speaks for it', () => {
    expect(phaseCommitsView(null, run)).toBeNull()
    expect(phaseCommitsView(null, null)).toBeNull()
  })

  it('shows a phase that recorded commits under a run that did not', () => {
    expect(phaseCommitsView(run, null)).not.toBeNull()
  })
})
