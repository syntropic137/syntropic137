/**
 * The repos the platform knows about, ready to list.
 *
 * Reads the existing endpoints, `/repos`, `/systems` and `/github/repos`,
 * rather than a read model of its own. A repo carries only its system's id, so
 * the name is joined here; a system the listing does not know (deleted, or the
 * systems request failed) falls back to its id rather than hiding the repo.
 *
 * Attachment is whether the GitHub App can reach the repo right now, which
 * only `/github/repos` knows. When that lookup fails the answer is unknown,
 * not "not attached".
 */

import { useEffect, useState } from 'react'
import {
  listAppAccessibleRepoNames,
  listRepos,
  listSystems,
  type RepoSummary,
  type SystemSummary,
} from '../api/repos'

export type Attachment = 'attached' | 'not-attached' | 'unknown'

export interface RepoRow {
  repoId: string
  fullName: string
  /** Name of the owning system, or null when the repo belongs to none. */
  system: string | null
  /** Whether a GitHub App installation can reach it, so the platform can act on it. */
  attachment: Attachment
  isPrivate: boolean
}

export type RepoListState =
  { kind: 'loading' } | { kind: 'error'; message: string } | { kind: 'ready'; repos: RepoRow[] }

/** `null` when App access could not be looked up. */
type AccessibleNames = ReadonlySet<string> | null

function attachmentOf(fullName: string, accessible: AccessibleNames): Attachment {
  if (accessible === null) return 'unknown'
  // GitHub treats owner/name case-insensitively.
  return accessible.has(fullName.toLowerCase()) ? 'attached' : 'not-attached'
}

function toRow(
  repo: RepoSummary,
  systemNames: Map<string, string>,
  accessible: AccessibleNames,
): RepoRow {
  const systemId = repo.system_id ?? ''
  return {
    repoId: repo.repo_id,
    fullName: repo.full_name || repo.repo_id,
    system: systemId ? (systemNames.get(systemId) ?? systemId) : null,
    attachment: attachmentOf(repo.full_name, accessible),
    isPrivate: repo.is_private ?? false,
  }
}

async function loadRepoRows(): Promise<RepoRow[]> {
  const [repos, systems, accessible] = await Promise.all([
    listRepos(),
    // Only names are at stake: the rows are still worth showing without them.
    listSystems().catch((error: unknown): SystemSummary[] => {
      console.error(error)
      return []
    }),
    listAppAccessibleRepoNames().then(
      (names): AccessibleNames => new Set(names.map((name) => name.toLowerCase())),
      (error: unknown): AccessibleNames => {
        console.error(error)
        return null
      },
    ),
  ])
  const systemNames = new Map(systems.map((s) => [s.system_id, s.name]))
  return repos
    .map((repo) => toRow(repo, systemNames, accessible))
    .sort((a, b) => a.fullName.localeCompare(b.fullName))
}

export function useRepoList(): RepoListState {
  const [state, setState] = useState<RepoListState>({ kind: 'loading' })

  useEffect(() => {
    let cancelled = false
    loadRepoRows()
      .then((repos) => {
        if (!cancelled) setState({ kind: 'ready', repos })
      })
      .catch((error: unknown) => {
        console.error(error)
        if (!cancelled) {
          setState({
            kind: 'error',
            message: error instanceof Error ? error.message : 'Failed to load repositories',
          })
        }
      })
    return () => {
      cancelled = true
    }
  }, [])

  return state
}
