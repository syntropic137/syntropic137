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
  /**
   * Stable React key for this row, assigned once when the row is parsed.
   *
   * It must survive a live prepend: an index-based key shifts for every
   * existing row the moment a commit arrives, remounting the whole list and
   * dropping keyboard focus from a link the user was on. sha alone is not
   * unique either (the same commit can arrive from the backfill and the live
   * stream, and a merge reports the same sha twice), so the id carries a
   * per-tab sequence number as well.
   */
  id: string
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

/**
 * A git sha is hex and nothing else. A short sha is 7 characters, a full one
 * is 40, so anything outside 7..40 hex characters is not a sha: `'???????'`
 * is exactly the placeholder this card exists to avoid, and `'   '` renders a
 * blank hash because the card slices the first 7 characters.
 */
const SHA_PATTERN = /^[0-9a-fA-F]{7,40}$/

function sha(...candidates: unknown[]): string | undefined {
  for (const value of candidates) {
    if (typeof value !== 'string') continue
    const trimmed = value.trim()
    if (SHA_PATTERN.test(trimmed)) return trimmed
  }
  return undefined
}

/** Per-tab row counter, so two rows for the same sha still get distinct keys. */
let rowSequence = 0

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
 * Returns null for anything that is not a commit with a plausible hex sha, so
 * the card never renders a placeholder or blank hash: the activity stream also
 * carries checkouts and pushes under `git_*`, and a producer can write junk
 * such as `{sha: '???????'}` or `{sha: '   '}`.
 */
export function toGitCommit(time: string, eventType: string, payload: unknown): GitEvent | null {
  if (eventType !== 'git_commit') return null
  const data = record(payload)
  const git = record(data.git)
  // Legacy rows spread facts over the top level and `context`; the backend's
  // reader (GitFacts._from_legacy in session_tools_converters.py) takes the sha
  // from sha / context.sha / commit_hash / merge_sha. Read the same spellings,
  // or a real legacy commit silently disappears from the card.
  const ctx = record(data.context)
  const commitSha = sha(data.commit_hash, git.sha, data.sha, ctx.sha, data.merge_sha)
  if (!commitSha) return null
  const timestamp = text(data.timestamp)
  rowSequence += 1
  return {
    id: `${commitSha}-${timestamp ?? time}-${rowSequence}`,
    time,
    event_type: eventType,
    data: {
      commit_hash: commitSha,
      message: text(data.message, git.message, data.commit_message, ctx.message, data.message_preview),
      author: text(data.author, git.author),
      repository: text(data.repository, git.repo, data.repo, ctx.repo),
      branch: text(data.branch, git.branch, ctx.branch),
      url: text(data.url),
      timestamp,
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
