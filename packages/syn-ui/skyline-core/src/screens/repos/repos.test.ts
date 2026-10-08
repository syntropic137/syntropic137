import { describe, expect, it } from 'vitest'
import { groupReposByOwner, repoCounts, repoRows } from './index'

describe('repoRows', () => {
  const repos = [
    { repo_id: 'r1', full_name: 'org/Alpha', provider: 'github', system_id: 's1', is_private: false },
    { repo_id: 'r2', full_name: 'org/beta', provider: 'gitlab', system_id: null, is_private: true },
    { repo_id: 'r3', full_name: 'org/gamma', provider: 'github', system_id: 's9', is_private: false },
  ]
  const systems = [{ system_id: 's1', name: 'Platform' }]

  it('merges registration, systems and app reach', () => {
    const rows = repoRows(repos, systems, { repos: [{ fullName: 'org/alpha', isPrivate: true }, { fullName: 'other/app-only', isPrivate: false }], complete: false })
    const by = Object.fromEntries(rows.map((r) => [r.fullName, r]))
    expect(by['org/Alpha']).toMatchObject({ attachment: 'attached', privacy: 'private', system: 'Platform', registered: true })
    expect(by['org/beta']).toMatchObject({ attachment: 'not-attached', privacy: 'private', system: null })
    expect(by['org/gamma']).toMatchObject({ attachment: 'unknown', privacy: 'unknown', system: 's9' })
    expect(by['other/app-only']).toMatchObject({ registered: false, attachment: 'attached', privacy: 'public', key: '@github-app|other/app-only', owner: 'other', name: 'app-only' })
    expect(rows.map((r) => r.fullName)).toEqual(['org/Alpha', 'org/beta', 'org/gamma', 'other/app-only'])
    expect(repoCounts(rows)).toEqual({ total: 4, attached: 2, unregistered: 1 })
    expect(groupReposByOwner(rows).map((g) => [g.owner, g.repos.length])).toEqual([
      ['org', 3],
      ['other', 1],
    ])
  })
  it('says not attached when the lookup was complete', () => {
    expect(repoRows([repos[2]!], [], { repos: [], complete: true })[0]!.attachment).toBe('not-attached')
  })
})
