/**
 * The repos the platform knows about, ready to list.
 *
 * Reads the existing organization endpoints, `/repos` and `/systems`, rather
 * than a read model of its own. A repo carries only its system's id, so the
 * name is joined here; a system the listing does not know (deleted, or the
 * systems request failed) falls back to its id rather than hiding the repo.
 */

import { useEffect, useState } from 'react'
import { listRepos, listSystems, type RepoSummary, type SystemSummary } from '../api/repos'

export interface RepoRow {
  repoId: string
  fullName: string
  /** Name of the owning system, or null when the repo belongs to none. */
  system: string | null
  /** Linked to a GitHub App installation, so the platform can act on it. */
  attached: boolean
  isPrivate: boolean
}

export type RepoListState =
  { kind: 'loading' } | { kind: 'error'; message: string } | { kind: 'ready'; repos: RepoRow[] }

function toRow(repo: RepoSummary, systemNames: Map<string, string>): RepoRow {
  const systemId = repo.system_id ?? ''
  return {
    repoId: repo.repo_id,
    fullName: repo.full_name || repo.repo_id,
    system: systemId ? (systemNames.get(systemId) ?? systemId) : null,
    attached: Boolean(repo.installation_id),
    isPrivate: repo.is_private ?? false,
  }
}

async function loadRepoRows(): Promise<RepoRow[]> {
  const [repos, systems] = await Promise.all([
    listRepos(),
    // Only names are at stake: the rows are still worth showing without them.
    listSystems().catch((error: unknown): SystemSummary[] => {
      console.error(error)
      return []
    }),
  ])
  const systemNames = new Map(systems.map((s) => [s.system_id, s.name]))
  return repos
    .map((repo) => toRow(repo, systemNames))
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
