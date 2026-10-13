/**
 * The bundle's version is the product version (lockstep since the cutover
 * release, docs/syn-ui-rollout.md), so a clean build behind an API of the same
 * release shows no mismatch, and one behind another release does.
 */
import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'
import { buildView, toPep440 } from '@syn137/skyline-core/screens/version'

const productVersion = (): string => {
  const pyproject = readFileSync(new URL('../../../../pyproject.toml', import.meta.url), 'utf-8')
  const m = /^version = "([^"]+)"$/m.exec(pyproject)
  if (!m?.[1]) throw new Error('root pyproject.toml has no version')
  return m[1]
}

const served = (version: string) => ({ version, started_at_display: '2026-10-09 00:00 UTC' })

describe('UI version lockstep', () => {
  it('stamps the product version into the bundle', () => {
    expect(__SYN_UI_VERSION__).not.toBe('0.0.0')
    expect(toPep440(__SYN_UI_VERSION__)).toBe(productVersion())
  })

  it('shows no mismatch behind an API of the same release', () => {
    expect(buildView(served(productVersion()), __SYN_UI_VERSION__).mismatch).toBe(false)
  })

  it('flags an API from another release', () => {
    expect(buildView(served('0.0.1b1'), __SYN_UI_VERSION__).mismatch).toBe(true)
  })
})
