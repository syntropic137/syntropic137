/**
 * The connected repos, ready to list.
 *
 * A repo is connected when it is registered (`/repos`) OR some GitHub App
 * installation can reach it (`/github/repos`); see "Connected Repo" in
 * docs/architecture/organization-ubiquitous-language.md. The list is the union
 * of the two, so a repo the App was installed on but nobody ran
 * `syn repo register` for still appears (feedback 29714ff9: the page showed
 * one repo of five because it listed `/repos` alone). Repos assigned to a
 * system are registered by definition, so `/systems` adds names, not rows; a
 * repo only named in some execution's inputs is not connected and not listed.
 *
 * Rows are keyed by `repo_id`, a registered repo's aggregate identity, and
 * never by its name. Two organizations that each registered `acme/api`, a
 * Gitea `acme/api` beside a GitHub one, and `Acme/API` beside `acme/api` in
 * one organization, are each distinct Repos, and keying by name silently
 * collapsed them: one row vanished, with its System. Repo uniqueness is a
 * claim on `(organization_id, provider, full_name)` taken with no case
 * folding (`aggregate_repo_claim/claim_id.py`), so even case-variant names
 * are two Repos.
 *
 * A repo carries only its system's id, so the name is joined here; a system
 * the listing does not know (deleted, or the systems request failed) falls back
 * to its id rather than hiding the repo.
 *
 * Attachment is whether the GitHub App can reach the repo right now, which
 * only `/github/repos` knows. A repo it lists is attached; a repo it omits is
 * "not attached" only when GitHub answered for every installation, and
 * unknown otherwise. `/github/repos` has no organization, so it is joined by
 * name, and only to repos whose provider is GitHub: the App can never reach a
 * Gitea or GitLab repo, whatever it is called.
 *
 * The App also reports the repo's live privacy, which is what the row shows
 * for a repo it reaches: `syn repo register` sends `is_private: false`
 * unconditionally, so the stored flag says "public" for every CLI-registered
 * repo and a private one rendered without its lock.
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

/** The only provider a GitHub App installation can reach. */
const GITHUB = 'github'

export interface RepoRow {
  /**
   * Row identity: a registered repo's `repo_id`, the Repo aggregate's own id.
   * An App-only repo has no Repo, so it is keyed `@github-app|<name>` with
   * the name folded. Never a registered repo's name: see above.
   */
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

/** What the App knows about a repo it reaches, by lower-cased full name. */
type AppEntries = ReadonlyMap<string, { isPrivate: boolean }>

function registeredRow(
  repo: RepoSummary,
  systemNames: Map<string, string>,
  access: AppAccess,
  appEntries: AppEntries,
): RepoRow {
  const fullName = repo.full_name || repo.repo_id
  const provider = (repo.provider || GITHUB).toLowerCase()
  const systemId = repo.system_id ?? ''
  // The App reaches GitHub repos only, so a repo on any other provider is
  // definitively not attached - the lookup being partial changes nothing.
  const app = provider === GITHUB ? appEntries.get(fullName.toLowerCase()) : undefined
  const attachment: Attachment = app
    ? 'attached'
    : provider !== GITHUB || access.complete
      ? 'not-attached'
      : 'unknown'
  return {
    key: repo.repo_id,
    fullName,
    registered: true,
    system: systemId ? (systemNames.get(systemId) ?? systemId) : null,
    attachment,
    // The App's answer is live; the stored flag is whatever registration sent,
    // and `syn repo register` always sends false.
    isPrivate: app ? app.isPrivate : (repo.is_private ?? false),
  }
}

/** The connected repos: registered ones first, then any only the App reaches. */
function connectedRepoRows(
  repos: RepoSummary[],
  systems: SystemSummary[],
  access: AppAccess,
): RepoRow[] {
  const systemNames = new Map(systems.map((s) => [s.system_id, s.name]))
  const appEntries: AppEntries = new Map(
    access.repos.map((r) => [r.fullName.toLowerCase(), { isPrivate: r.isPrivate }]),
  )
  const rows = new Map<string, RepoRow>()
  // Names already covered by a registered GitHub repo, whichever organization
  // registered it: the App reports no organization, so one of its repos can
  // only be matched by name.
  const registeredGitHubNames = new Set<string>()
  for (const repo of repos) {
    const row = registeredRow(repo, systemNames, access, appEntries)
    rows.set(row.key, row)
    if ((repo.provider || GITHUB).toLowerCase() === GITHUB) {
      registeredGitHubNames.add(row.fullName.toLowerCase())
    }
  }
  for (const { fullName, isPrivate } of access.repos) {
    const name = fullName.toLowerCase()
    if (registeredGitHubNames.has(name)) continue
    // No Repo exists for it, so there is no repo_id to key it by. GitHub
    // names are case-insensitive, so the App's own name is folded here.
    const key = `@github-app|${name}`
    rows.set(key, {
      key,
      fullName,
      registered: false,
      system: null,
      attachment: 'attached',
      isPrivate,
    })
  }
  return [...rows.values()].sort(
    (a, b) => a.fullName.localeCompare(b.fullName) || a.key.localeCompare(b.key),
  )
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
