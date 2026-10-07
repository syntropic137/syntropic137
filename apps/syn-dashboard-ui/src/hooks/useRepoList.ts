/**
 * The connected repos, ready to list.
 *
 * A repo is connected when it is registered (`/repos`) OR some GitHub App
 * installation can reach it (`/github/repos`); see "Connected Repo" in
 * docs/architecture/organization-ubiquitous-language.md. The list is the union
 * of the two, keyed by full name, so a repo the App was installed on but nobody
 * ran `syn repo register` for still appears (feedback 29714ff9: the page showed
 * one repo of five because it listed `/repos` alone). Repos assigned to a
 * system are registered by definition, so `/systems` adds names, not rows; a
 * repo only named in some execution's inputs is not connected and not listed.
 *
 * A repo carries only its system's id, so the name is joined here; a system
 * the listing does not know (deleted, or the systems request failed) falls back
 * to its id rather than hiding the repo.
 *
 * Attachment is whether the GitHub App can reach the repo right now, which
 * only `/github/repos` knows. A repo it lists is attached; a repo it omits is
 * "not attached" only when GitHub answered for every installation, and
 * unknown otherwise.
 */

import { useEffect, useState } from 'react'
import {
  listRepos,
  lookUpAppAccess,
  listSystems,
  type AppAccess,
  type RepoSummary,
  type SystemSummary,
} from '../api/repos'

export type Attachment = 'attached' | 'not-attached' | 'unknown'

export interface RepoRow {
  /** Lower-cased full name: GitHub treats owner/name case-insensitively. */
  key: string
  fullName: string
  /** Whether a `Repo` aggregate exists for it; false when only the App reaches it. */
  registered: boolean
  /** Name of the owning system, or null when the repo belongs to none. */
  system: string | null
  /** Whether a GitHub App installation can reach it, so the platform can act on it. */
  attachment: Attachment
  isPrivate: boolean
}

export type RepoListState =
  { kind: 'loading' } | { kind: 'error'; message: string } | { kind: 'ready'; repos: RepoRow[] }

const UNKNOWN_ACCESS: AppAccess = { repos: [], complete: false }

function registeredRow(
  repo: RepoSummary,
  systemNames: Map<string, string>,
  access: AppAccess,
  reachable: ReadonlySet<string>,
): RepoRow {
  const fullName = repo.full_name || repo.repo_id
  const key = fullName.toLowerCase()
  const systemId = repo.system_id ?? ''
  return {
    key,
    fullName,
    registered: true,
    system: systemId ? (systemNames.get(systemId) ?? systemId) : null,
    attachment: reachable.has(key) ? 'attached' : access.complete ? 'not-attached' : 'unknown',
    isPrivate: repo.is_private ?? false,
  }
}

/** The connected repos: registered ones first, then any only the App reaches. */
function connectedRepoRows(
  repos: RepoSummary[],
  systems: SystemSummary[],
  access: AppAccess,
): RepoRow[] {
  const systemNames = new Map(systems.map((s) => [s.system_id, s.name]))
  const reachable = new Set(access.repos.map((r) => r.fullName.toLowerCase()))
  const rows = new Map<string, RepoRow>()
  for (const repo of repos) {
    const row = registeredRow(repo, systemNames, access, reachable)
    rows.set(row.key, row)
  }
  for (const { fullName, isPrivate } of access.repos) {
    const key = fullName.toLowerCase()
    if (rows.has(key)) continue
    rows.set(key, {
      key,
      fullName,
      registered: false,
      system: null,
      attachment: 'attached',
      isPrivate,
    })
  }
  return [...rows.values()].sort((a, b) => a.fullName.localeCompare(b.fullName))
}

async function loadRepoRows(): Promise<RepoRow[]> {
  const [repos, systems, access] = await Promise.all([
    listRepos(),
    // Only names are at stake: the rows are still worth showing without them.
    listSystems().catch((error: unknown): SystemSummary[] => {
      console.error(error)
      return []
    }),
    lookUpAppAccess().catch((error: unknown): AppAccess => {
      console.error(error)
      return UNKNOWN_ACCESS
    }),
  ])
  return connectedRepoRows(repos, systems, access)
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
