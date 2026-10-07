import { describe, expect, it } from 'vitest'

import { shortRef, sourceRepoLabel, sourceUrlAtRef } from '../skillRefs'

const SHA = '7e48aad9c7186bb03b8b0df899f56b7cd3b2a454'

describe('shortRef', () => {
  it('abbreviates a full commit SHA', () => {
    expect(shortRef(SHA)).toBe('7e48aad')
  })

  it.each(['v2.3.1', 'main', 'release-2026', 'deadbeef'])('leaves %s as written', (ref) => {
    expect(shortRef(ref)).toBe(ref)
  })
})

describe('sourceRepoLabel', () => {
  it('names a GitHub source by org/repo', () => {
    expect(sourceRepoLabel('https://github.com/syntropic137/software-leverage-points.git')).toBe(
      'syntropic137/software-leverage-points',
    )
  })

  // What `SkillRef` keeps as `source_url` for its ssh spellings.
  it.each(['git@github.com:org/skills', 'git+ssh://git@github.com/org/skills', 'ssh://git@github.com/org/skills.git'])(
    'names an ssh GitHub source %s by org/repo',
    (url) => {
      expect(sourceRepoLabel(url)).toBe('org/skills')
    },
  )

  it('shows any other source as given', () => {
    expect(sourceRepoLabel('git@gitlab.com:org/repo.git')).toBe('git@gitlab.com:org/repo.git')
  })
})

describe('sourceUrlAtRef', () => {
  it('links the GitHub tree at exactly that ref', () => {
    expect(sourceUrlAtRef('https://github.com/anthropics/skills', SHA)).toBe(
      `https://github.com/anthropics/skills/tree/${SHA}`,
    )
  })

  it.each(['git@github.com:org/skills', 'git+ssh://git@github.com/org/skills'])(
    'links an ssh GitHub source %s over https',
    (url) => {
      expect(sourceUrlAtRef(url, 'v1')).toBe('https://github.com/org/skills/tree/v1')
    },
  )

  it.each([
    ['a non-GitHub host', 'https://gitlab.com/org/repo'],
    ['an ssh source on another host', 'git@gitlab.com:org/repo.git'],
    ['a URL that is not a repo root', 'https://github.com/org'],
  ])('builds no link for %s', (_why, url) => {
    expect(sourceUrlAtRef(url, SHA)).toBeNull()
  })

  it('builds no link for a version pinned by content hash, which is no git ref', () => {
    expect(sourceUrlAtRef('https://github.com/org/skills', `sha256-${'a'.repeat(64)}`)).toBeNull()
  })
})
