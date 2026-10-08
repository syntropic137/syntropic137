/**
 * The home "Live Commits" card shows a real hash for every row (feedback
 * f96a9197: "always has question marks").
 *
 * Agent commits arrive nested (`data.git.sha`, agentic_events GitCommitPayload)
 * and the live stream also carries checkouts and pushes. The card read only the
 * webhook's flat `commit_hash`, so both rendered `???????`.
 */
import { act, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import type { SSEEventFrame } from '../../types'
import { EventFeed } from '../EventFeed'
import { toGitCommit } from '../../hooks/useEventFeed'

let pushFrame: ((frame: SSEEventFrame) => void) | null = null

vi.mock('../../hooks/useActivityStream', () => ({
  useActivityStream: (options: {
    onEvent: (frame: SSEEventFrame) => void
    filter?: (eventType: string) => boolean
  }) => {
    pushFrame = (frame) => {
      if (!options.filter || options.filter(frame.event_type)) options.onEvent(frame)
    }
    return { connected: true }
  },
}))

const RECENT = [
  {
    time: '2026-10-06T10:00:00Z',
    event_type: 'git_commit',
    data: { git: { operation: 'commit', sha: 'a1b2c3d4e5f6', message: 'agent nested commit', repo: 'syntropic137', branch: 'fix/x' } },
  },
  {
    time: '2026-10-06T09:00:00Z',
    event_type: 'git_commit',
    data: { commit_hash: 'feedface0000', message: 'webhook flat commit', repository: 'acme/api', branch: 'main', url: 'https://github.com/acme/api/commit/feedface0000' },
  },
  {
    time: '2026-10-06T08:00:00Z',
    event_type: 'git_commit',
    data: { sha: 'cafebabe1111', commit_message: 'legacy agent commit' },
  },
  {
    // Legacy shape with the sha only under `context` (the backend's
    // GitFacts._from_legacy reads context.sha); review of #1668.
    time: '2026-10-06T07:00:00Z',
    event_type: 'git_commit',
    data: { context: { sha: 'deadbeef2222', message: 'context-only legacy commit', branch: 'main' } },
  },
]

beforeEach(() => {
  vi.stubGlobal(
    'fetch',
    vi.fn(async () => new Response(JSON.stringify({ events: RECENT }), { status: 200 })),
  )
})

afterEach(() => {
  vi.unstubAllGlobals()
  pushFrame = null
})

function frame(event_type: string, data: Record<string, unknown>): SSEEventFrame {
  return { type: 'event', event_type, execution_id: null, data, timestamp: '2026-10-06T11:00:00Z' }
}

describe('EventFeed', () => {
  it('shows the hash and message of commits in every producer shape', async () => {
    render(<EventFeed />)
    await waitFor(() => expect(screen.getByText('a1b2c3d')).toBeTruthy())
    expect(screen.getByText('agent nested commit')).toBeTruthy()
    expect(screen.getByText('feedfac')).toBeTruthy()
    expect(screen.getByText('cafebab')).toBeTruthy()
    expect(screen.getByText('legacy agent commit')).toBeTruthy()
    expect(screen.getByText('deadbee')).toBeTruthy()
    expect(screen.getByText('context-only legacy commit')).toBeTruthy()
    expect(screen.queryByText(/\?\?\?/)).toBeNull()
  })

  it('adds live agent commits and ignores git frames that are not commits', async () => {
    render(<EventFeed />)
    await waitFor(() => expect(screen.getByText('a1b2c3d')).toBeTruthy())
    act(() => {
      pushFrame?.(frame('git_checkout', { git: { operation: 'checkout', branch: 'main', sha: '0123456789ab' } }))
      pushFrame?.(frame('git_push', { git: { operation: 'push', branch: 'main' } }))
      pushFrame?.(frame('git_commit', { git: { operation: 'commit', sha: '9876543210ff', message: 'live one' } }))
    })
    expect(screen.getByText('9876543')).toBeTruthy()
    expect(screen.queryByText('0123456')).toBeNull()
    expect(screen.queryByText(/\?\?\?/)).toBeNull()
  })

  it('drops rows whose sha is a placeholder, blank, or not hex', async () => {
    render(<EventFeed />)
    await waitFor(() => expect(screen.getByText('a1b2c3d')).toBeTruthy())
    act(() => {
      // The exact placeholder this card exists to eliminate.
      pushFrame?.(frame('git_commit', { sha: '???????', message: 'placeholder sha' }))
      // Whitespace renders a blank hash, because the card slices 7 characters.
      pushFrame?.(frame('git_commit', { sha: '   ', message: 'blank sha' }))
      // Non-hex, and too short to be even a short sha.
      pushFrame?.(frame('git_commit', { commit_hash: 'not-a-sha!', message: 'non hex sha' }))
      pushFrame?.(frame('git_commit', { commit_hash: 'abc123', message: 'too short sha' }))
      // Longer than a full sha.
      pushFrame?.(frame('git_commit', { commit_hash: 'a'.repeat(41), message: 'too long sha' }))
    })
    expect(screen.queryByText(/\?\?\?/)).toBeNull()
    expect(screen.queryByText('placeholder sha')).toBeNull()
    expect(screen.queryByText('blank sha')).toBeNull()
    expect(screen.queryByText('non hex sha')).toBeNull()
    expect(screen.queryByText('too short sha')).toBeNull()
    expect(screen.queryByText('too long sha')).toBeNull()
  })

  it('accepts a 7-character short sha, a full 40-character sha, and trims padding', async () => {
    render(<EventFeed />)
    await waitFor(() => expect(screen.getByText('a1b2c3d')).toBeTruthy())
    act(() => {
      pushFrame?.(frame('git_commit', { sha: '1234567', message: 'short sha' }))
      pushFrame?.(frame('git_commit', { sha: 'b'.repeat(40), message: 'full sha' }))
      pushFrame?.(frame('git_commit', { sha: '  C0FFEE1  ', message: 'padded uppercase sha' }))
    })
    expect(screen.getByText('1234567')).toBeTruthy()
    expect(screen.getByText('bbbbbbb')).toBeTruthy()
    expect(screen.getByText('C0FFEE1')).toBeTruthy()
  })

  it('keeps keyboard focus on an existing row when a live commit is prepended', async () => {
    render(<EventFeed />)
    await waitFor(() => expect(screen.getByText('feedfac')).toBeTruthy())
    const link = screen.getByTitle('View on GitHub')
    link.focus()
    expect(document.activeElement).toBe(link)
    act(() => {
      pushFrame?.(frame('git_commit', { git: { operation: 'commit', sha: '0f0f0f0f0f0f', message: 'prepended' } }))
    })
    expect(screen.getByText('0f0f0f0')).toBeTruthy()
    // An index-based key shifts every existing row's key here, remounting the
    // row and detaching the focused link.
    expect(document.activeElement).toBe(link)
    expect(screen.getByTitle('View on GitHub')).toBe(link)
  })

  it('renders two rows for the same sha without a duplicate-key collision', async () => {
    const errors: unknown[] = []
    const spy = vi.spyOn(console, 'error').mockImplementation((...args: unknown[]) => {
      errors.push(args[0])
    })
    render(<EventFeed />)
    await waitFor(() => expect(screen.getByText('a1b2c3d')).toBeTruthy())
    act(() => {
      pushFrame?.(frame('git_commit', { sha: 'abcdef1234567', message: 'first' }))
      pushFrame?.(frame('git_commit', { sha: 'abcdef1234567', message: 'second' }))
    })
    expect(screen.getAllByText('abcdef1')).toHaveLength(2)
    expect(errors.filter((e) => String(e).includes('same key'))).toHaveLength(0)
    spy.mockRestore()
  })
})

describe('toGitCommit', () => {
  it('returns null without throwing for shapes that are not commit payloads', () => {
    expect(toGitCommit('t', 'git_commit', null)).toBeNull()
    expect(toGitCommit('t', 'git_commit', undefined)).toBeNull()
    expect(toGitCommit('t', 'git_commit', [])).toBeNull()
    expect(toGitCommit('t', 'git_commit', ['a1b2c3d4e5f6'])).toBeNull()
    expect(toGitCommit('t', 'git_commit', 'a1b2c3d4e5f6')).toBeNull()
    expect(toGitCommit('t', 'git_commit', 42)).toBeNull()
    expect(toGitCommit('t', 'git_commit', { git: null })).toBeNull()
    expect(toGitCommit('t', 'git_commit', { git: 'a1b2c3d4e5f6' })).toBeNull()
    expect(toGitCommit('t', 'git_commit', { git: ['a1b2c3d4e5f6'] })).toBeNull()
    expect(toGitCommit('t', 'git_commit', { context: 7 })).toBeNull()
    expect(toGitCommit('t', 'git_commit', { sha: 123456789 })).toBeNull()
    expect(toGitCommit('t', 'git_commit', { commit_hash: { toString: () => 'a1b2c3d' } })).toBeNull()
    expect(toGitCommit('t', 'git_checkout', { sha: 'a1b2c3d4e5f6' })).toBeNull()
  })

  it('gives two rows for the same sha and timestamp distinct ids', () => {
    const payload = { sha: 'a1b2c3d4e5f6', timestamp: '2026-10-06T10:00:00Z' }
    const first = toGitCommit('t', 'git_commit', payload)
    const second = toGitCommit('t', 'git_commit', payload)
    expect(first?.id).toBeTruthy()
    expect(first?.id).not.toEqual(second?.id)
  })
})
