import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { configureClient } from '../client'
import { getBuildInfo } from '../resources/observability'

beforeEach(() => {
  configureClient({ fixtures: true, fixtureLatencyMs: 0 })
})
afterEach(() => {
  configureClient({ fixtures: false, fixtureLatencyMs: 120 })
})

describe('build info fixture', () => {
  it('reads like a real deploy: PEP 440 version, semver tag, full sha, display matching started_at', async () => {
    const b = await getBuildInfo()
    expect(b.version).toMatch(/^\d+\.\d+\.\d+(?:(?:a|b|rc)\d+)?$/)
    expect(b.image_tag).toBe(`v${b.version!.replace(/b(\d+)$/, '-beta.$1')}`)
    expect(b.commit).toMatch(/^[0-9a-f]{40}$/)
    expect(b.version_status).toBe('installed')
    const at = new Date(b.started_at)
    const display = `${at.toISOString().slice(0, 10)} ${at.toISOString().slice(11, 16)} UTC`
    expect(b.started_at_display).toBe(display)
  })
})
