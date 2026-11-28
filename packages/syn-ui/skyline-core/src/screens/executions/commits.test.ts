import { describe, expect, it } from 'vitest'
import { COMMITS_NOT_RECORDED, type SourceCommitLike, commitsView, phaseCommitsView } from './detail'

const SHA = '4f2a9c1e88d07b3a5c6d7e8f9a0b1c2d3e4f5a6b'
const OTHER = '9b8a7c6d5e4f3a2b1c0d9e8f7a6b5c4d3e2f1a0b'
const THIRD = '1a2b3c4d5e6f7a8b9c0d1e2f3a4b5c6d7e8f9a0b'
// The API's `sha_display` for each, as `SourceCommitResponse` serves it.
const SHORT: Record<string, string> = { [SHA]: '4f2a9c1', [OTHER]: '9b8a7c6', [THIRD]: '1a2b3c4' }
const at = (repository: string, sha: string | null): SourceCommitLike => ({ repository, sha, sha_display: sha && SHORT[sha]! })

const ran = (checked_out_commits: SourceCommitLike[] | null | undefined) => ({ status: 'completed', checked_out_commits })
const texts = (view: ReturnType<typeof phaseCommitsView>) => (view?.kind === 'commits' ? view.lines.map((l) => l.text) : view)

describe('commitsView (#1004)', () => {
  it('says a run from before capture did not record a commit, never an empty list', () => {
    expect(commitsView(null)).toEqual({ kind: 'absent', text: COMMITS_NOT_RECORDED })
    expect(commitsView(undefined)).toEqual({ kind: 'absent', text: COMMITS_NOT_RECORDED })
  })

  it('says a run that checked nothing out in words', () => {
    expect(commitsView([])).toEqual({ kind: 'absent', text: 'no repository checked out' })
  })

  it("shows the API's short SHA, and keeps the full SHA to copy (#897)", () => {
    expect(commitsView([{ repository: 'acme/service', sha: SHA, sha_display: 'shown-7' }])).toEqual({
      kind: 'commits',
      lines: [{ repository: 'acme/service', sha: SHA, text: 'acme/service @ shown-7' }],
    })
  })

  it('says a recorded but unresolved commit is unresolved, never a blank', () => {
    const view = commitsView([at('acme/web', null), { repository: 'acme/cli' }])
    expect(view).toEqual({
      kind: 'commits',
      lines: [
        { repository: 'acme/web', sha: null, text: 'acme/web @ unresolved' },
        { repository: 'acme/cli', sha: null, text: 'acme/cli @ unresolved' },
      ],
    })
  })
})

describe('phaseCommitsView (#1004)', () => {
  const run = [
    at('acme/service', SHA),
    at('acme/web', null),
  ]

  it('says nothing for a phase checked out where the run was, in any order', () => {
    expect(phaseCommitsView(ran([...run].reverse()), run)).toBeNull()
  })

  it('shows only the repository that differs, never the ones that match the run', () => {
    expect(texts(phaseCommitsView(ran([at('acme/service', OTHER), run[1]!]), run))).toEqual(['acme/service @ 9b8a7c6'])
  })

  it('shows the second repository alone when only it changed', () => {
    const two = [
      at('org/one', SHA),
      at('org/two', OTHER),
    ]
    expect(texts(phaseCommitsView(ran([two[0]!, at('org/two', THIRD)]), two))).toEqual(['org/two @ 1a2b3c4'])
  })

  it('every line it shows differs from the run for that repository', () => {
    const shas = [SHA, OTHER, THIRD, null]
    for (const a of shas)
      for (const b of shas) {
        const phase = [
          at('org/one', a),
          at('org/two', b),
        ]
        const view = phaseCommitsView(ran(phase), run.map((c, i) => ({ ...c, repository: i ? 'org/two' : 'org/one' })))
        const execution = new Map([
          ['org/one', SHA],
          ['org/two', null],
        ])
        for (const line of view?.kind === 'commits' ? view.lines : []) expect(line.sha).not.toBe(execution.get(line.repository))
        const changed = phase.filter((c) => c.sha !== execution.get(c.repository)).length
        expect(view?.kind === 'commits' ? view.lines.length : 0).toBe(changed)
      }
  })

  it('shows a phase whose unresolved commit resolved', () => {
    expect(texts(phaseCommitsView(ran([run[0]!, at('acme/web', OTHER)]), run))).toEqual(['acme/web @ 9b8a7c6'])
  })

  it('says a phase that ran without recording commits did not record them, under a run that did', () => {
    expect(phaseCommitsView(ran(null), run)).toEqual({ kind: 'absent', text: COMMITS_NOT_RECORDED })
    expect(phaseCommitsView(ran(undefined), run)).toEqual({ kind: 'absent', text: COMMITS_NOT_RECORDED })
  })

  it('says a phase that ran without recording commits did not record them, under a run that did not either', () => {
    expect(phaseCommitsView(ran(null), null)).toEqual({ kind: 'absent', text: COMMITS_NOT_RECORDED })
  })

  it('says nothing for a phase not started yet', () => {
    expect(phaseCommitsView({ status: 'pending', checked_out_commits: null }, run)).toBeNull()
    expect(phaseCommitsView({ status: 'pending', checked_out_commits: null }, null)).toBeNull()
  })

  it('shows every commit of a phase that recorded them under a run that did not', () => {
    expect(texts(phaseCommitsView(ran(run), null))).toEqual(['acme/service @ 4f2a9c1', 'acme/web @ unresolved'])
  })
})
