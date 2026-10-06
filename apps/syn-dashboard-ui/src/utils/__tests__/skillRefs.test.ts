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

  it.each([
    ['a non-GitHub host', 'https://gitlab.com/org/repo'],
    ['an ssh source', 'git@github.com:org/repo.git'],
    ['a URL that is not a repo root', 'https://github.com/org'],
  ])('builds no link for %s', (_why, url) => {
    expect(sourceUrlAtRef(url, SHA)).toBeNull()
  })
})
