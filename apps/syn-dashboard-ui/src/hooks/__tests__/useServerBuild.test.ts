import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { renderHook } from '@testing-library/react'

import type { BuildInfo } from '../../api'
import { BUILD_POLL_INTERVAL_MS, useServerBuild } from '../useServerBuild'

vi.mock('../../api', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../../api')>()),
  getBuildInfo: vi.fn(),
}))

import { getBuildInfo } from '../../api'

const mockGetBuildInfo = vi.mocked(getBuildInfo)

const makeBuild = (overrides: Partial<BuildInfo> = {}): BuildInfo => ({
  version: '0.33.0b1',
  version_status: 'installed',
  image_tag: 'v0.33.0-beta.1',
  commit: '9f3c1ab2d4e5',
  started_at: '2031-02-03T04:05:06Z',
  started_at_display: '2031-02-03 04:05 UTC',
  ...overrides,
})

function setVisibility(state: 'visible' | 'hidden') {
  Object.defineProperty(document, 'visibilityState', { value: state, configurable: true })
}

describe('useServerBuild', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.useFakeTimers()
    setVisibility('visible')
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('fetches on mount and reports the server build, not the bundle', async () => {
    mockGetBuildInfo.mockResolvedValue(makeBuild())

    const { result } = renderHook(() => useServerBuild('0.33.0-beta.1'))

    expect(result.current.build).toBeNull()
    await vi.waitFor(() => expect(result.current.build?.image_tag).toBe('v0.33.0-beta.1'))
    expect(mockGetBuildInfo).toHaveBeenCalledTimes(1)
  })

  it('refetches on the poll interval and not before it', async () => {
    mockGetBuildInfo.mockResolvedValue(makeBuild())

    const { result } = renderHook(() => useServerBuild('0.33.0-beta.1'))
    await vi.waitFor(() => expect(result.current.build).not.toBeNull())
    expect(mockGetBuildInfo).toHaveBeenCalledTimes(1)

    await vi.advanceTimersByTimeAsync(BUILD_POLL_INTERVAL_MS - 1000)
    expect(mockGetBuildInfo).toHaveBeenCalledTimes(1)

    await vi.advanceTimersByTimeAsync(1000)
    expect(mockGetBuildInfo).toHaveBeenCalledTimes(2)

    await vi.advanceTimersByTimeAsync(BUILD_POLL_INTERVAL_MS)
    expect(mockGetBuildInfo).toHaveBeenCalledTimes(3)
  })

  it('does not poll while hidden, and refetches as soon as the tab is visible again', async () => {
    mockGetBuildInfo.mockResolvedValue(makeBuild())

    const { result } = renderHook(() => useServerBuild('0.33.0-beta.1'))
    await vi.waitFor(() => expect(result.current.build).not.toBeNull())

    setVisibility('hidden')
    document.dispatchEvent(new Event('visibilitychange'))
    await vi.advanceTimersByTimeAsync(BUILD_POLL_INTERVAL_MS * 3)
    expect(mockGetBuildInfo).toHaveBeenCalledTimes(1)

    setVisibility('visible')
    document.dispatchEvent(new Event('visibilitychange'))
    await vi.waitFor(() => expect(mockGetBuildInfo).toHaveBeenCalledTimes(2))
  })

  it('treats the PEP 440 and semver spellings of one release as the same build', async () => {
    mockGetBuildInfo.mockResolvedValue(makeBuild({ version: '0.33.0b1' }))

    const { result } = renderHook(() => useServerBuild('0.33.0-beta.1'))
    await vi.waitFor(() => expect(result.current.build).not.toBeNull())

    expect(result.current.bundleIsStale).toBe(false)
  })

  it('flags the bundle as stale when a new release is deployed while the page is open', async () => {
    mockGetBuildInfo.mockResolvedValue(makeBuild({ version: '0.33.0b1' }))

    const { result } = renderHook(() => useServerBuild('0.33.0-beta.1'))
    await vi.waitFor(() => expect(result.current.build).not.toBeNull())
    expect(result.current.bundleIsStale).toBe(false)

    mockGetBuildInfo.mockResolvedValue(
      makeBuild({ version: '0.34.0', image_tag: 'v0.34.0', started_at: '2031-02-03T09:00:00Z' }),
    )
    await vi.advanceTimersByTimeAsync(BUILD_POLL_INTERVAL_MS)

    await vi.waitFor(() => expect(result.current.build?.image_tag).toBe('v0.34.0'))
    expect(result.current.bundleIsStale).toBe(true)
  })

  it('does not call an unreadable server release a new version', async () => {
    mockGetBuildInfo.mockResolvedValue(makeBuild({ version: null, version_status: 'unavailable' }))

    const { result } = renderHook(() => useServerBuild('0.33.0-beta.1'))
    await vi.waitFor(() => expect(result.current.build).not.toBeNull())

    expect(result.current.bundleIsStale).toBe(false)
  })

  it('keeps the last known build when a later fetch fails', async () => {
    mockGetBuildInfo.mockResolvedValue(makeBuild())

    const { result } = renderHook(() => useServerBuild('0.33.0-beta.1'))
    await vi.waitFor(() => expect(result.current.build).not.toBeNull())

    mockGetBuildInfo.mockRejectedValue(new Error('502'))
    await vi.advanceTimersByTimeAsync(BUILD_POLL_INTERVAL_MS)
    expect(mockGetBuildInfo).toHaveBeenCalledTimes(2)

    expect(result.current.build?.image_tag).toBe('v0.33.0-beta.1')
  })
})
