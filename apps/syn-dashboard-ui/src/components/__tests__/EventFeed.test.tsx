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
    data: { commit_hash: 'feedface0000', message: 'webhook flat commit', repository: 'acme/api', branch: 'main' },
  },
  {
    time: '2026-10-06T08:00:00Z',
    event_type: 'git_commit',
    data: { sha: 'cafebabe1111', commit_message: 'legacy agent commit' },
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
})
