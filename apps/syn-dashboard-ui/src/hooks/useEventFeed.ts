/**
 * Live git event feed.
 *
 * Loads recent git events on mount and subscribes to the shared activity
 * stream (`useActivityStream`) so the dashboard opens at most one
 * `EventSource` per tab even when multiple consumers want activity events.
 *
 * See: docs/adrs/ADR-064-observability-monitor-ui.md
 */

import { useCallback, useEffect, useState } from 'react'
import { API_BASE } from '../api/client'
import { useActivityStream } from './useActivityStream'
import type { SSEEventFrame } from '../types'

/** A commit, read out of whichever shape its producer wrote. */
export interface GitEvent {
  time: string
  event_type: string
  data: {
    commit_hash: string
    message?: string
    author?: string
    repository?: string
    branch?: string
    url?: string
    timestamp?: string
  }
}

function text(...candidates: unknown[]): string | undefined {
  for (const value of candidates) {
    if (typeof value === 'string' && value) return value
  }
  return undefined
}

function record(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' ? (value as Record<string, unknown>) : {}
}

/**
 * Two producers write `git_commit` rows (feedback f96a9197): the GitHub push
 * webhook writes flat `{commit_hash, message, ...}`; an agent committing in its
 * workspace writes `{git: {sha, message, repo, ...}}` (agentic_events
 * GitCommitPayload), or flat `{sha, commit_message}` from older hooks. The
 * card read only `commit_hash`, so every agent commit showed `???????`.
 *
 * Returns null for anything that is not a commit with a sha, so the card never
 * renders a placeholder hash: the activity stream also carries checkouts and
 * pushes under `git_*`.
 */
export function toGitCommit(time: string, eventType: string, payload: unknown): GitEvent | null {
  if (eventType !== 'git_commit') return null
  const data = record(payload)
  const git = record(data.git)
  const sha = text(data.commit_hash, git.sha, data.sha)
  if (!sha) return null
  return {
    time,
    event_type: eventType,
    data: {
      commit_hash: sha,
      message: text(data.message, git.message, data.commit_message),
      author: text(data.author, git.author),
      repository: text(data.repository, git.repo, data.repo),
      branch: text(data.branch, git.branch),
      url: text(data.url),
      timestamp: text(data.timestamp),
    },
  }
}

interface RecentEventRow {
  time?: unknown
  event_type?: unknown
  data?: unknown
}

export interface UseEventFeedResult {
  events: GitEvent[]
  connected: boolean
}

export function useEventFeed(): UseEventFeedResult {
  const [events, setEvents] = useState<GitEvent[]>([])

  useEffect(() => {
    fetch(`${API_BASE}/events/recent?limit=30&event_type=git_commit`)
      .then((r) => r.json())
      .then((body: { events?: RecentEventRow[] }) => {
        const commits = (body.events ?? []).flatMap((row) => {
          const commit = toGitCommit(String(row.time ?? ''), String(row.event_type ?? ''), row.data)
          return commit ? [commit] : []
        })
        setEvents(commits)
      })
      .catch(() => {/* non-fatal */})
  }, [])

  const handleFrame = useCallback((frame: SSEEventFrame) => {
    if (frame.type !== 'event') return
    const commit = toGitCommit(frame.timestamp, frame.event_type, frame.data)
    if (commit) setEvents((prev) => [commit, ...prev].slice(0, 100))
  }, [])

  const { connected } = useActivityStream({
    onEvent: handleFrame,
    filter: (eventType) => eventType === 'git_commit',
  })

  return { events, connected }
}
