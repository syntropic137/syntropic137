import { describe, expect, it } from 'vitest'
import { buildView, isSameRelease, toPep440 } from './build'

const served = {
  version: '0.33.2b23',
  image_tag: 'v0.33.2-beta.23',
  commit: '996bbef0a463eddaf918576b46e051adb9aeab0b',
  started_at_display: '2026-10-09 00:39 UTC',
}

describe('toPep440 / isSameRelease', () => {
  it('maps semver prereleases to PEP 440', () => {
    expect(toPep440('0.33.2-beta.23')).toBe('0.33.2b23')
    expect(toPep440('v1.0.0-rc.1')).toBe('1.0.0rc1')
    expect(toPep440('0.4.0-alpha.02')).toBe('0.4.0a2')
    expect(isSameRelease('0.33.2-beta.23', '0.33.2b23')).toBe(true)
    expect(isSameRelease('0.33.2', '0.33.2b23')).toBe(false)
  })
})

describe('buildView', () => {
  it('labels the API release and lists the build', () => {
    const v = buildView(served, '0.33.2-beta.23')
    expect(v.label).toBe('v0.33.2b23')
    expect(v.commit).toBe('996bbef')
    expect(v.mismatch).toBe(false)
    expect(v.details).toEqual([
      { term: 'API', value: 'v0.33.2b23' },
      { term: 'Image', value: 'v0.33.2-beta.23' },
      { term: 'Commit', value: '996bbef' },
      { term: 'Deployed', value: '2026-10-09 00:39 UTC' },
      { term: 'UI', value: 'v0.33.2b23' },
    ])
    expect(v.text).toBe('Build: API v0.33.2b23 · Image v0.33.2-beta.23 · Commit 996bbef · Deployed 2026-10-09 00:39 UTC · UI v0.33.2b23')
  })
  it('flags a bundle from another release', () => {
    expect(buildView(served, '0.33.1').mismatch).toBe(true)
  })
  it('never flags an unversioned bundle', () => {
    const v = buildView(served, '0.0.0')
    expect(v.mismatch).toBe(false)
    expect(v.ui).toBeNull()
    expect(v.details.at(-1)).toEqual({ term: 'UI', value: 'unversioned' })
  })
  it('omits unstamped fields and waits for the API', () => {
    const v = buildView({ version: null, started_at_display: '2026-10-09 00:39 UTC' }, '0.0.0')
    expect(v.label).toBeNull()
    expect(v.commit).toBeNull()
    expect(v.details.map((d) => d.term)).toEqual(['API', 'Deployed', 'UI'])
    expect(buildView(undefined, '0.33.2').text).toBe('Build: API unknown · UI v0.33.2')
  })
})
