import type { components } from '../generated/api-types'
import { API_BASE, fetchJSON } from './base'

export type RepoSummary = components['schemas']['RepoSummaryResponse']
export type SystemSummary = components['schemas']['SystemSummaryResponse']

/** Every repo registered with the platform, across organizations. */
export async function listRepos(): Promise<RepoSummary[]> {
  const response = await fetchJSON<components['schemas']['RepoListResponse']>(`${API_BASE}/repos`)
  return response.repos ?? []
}

export async function listSystems(): Promise<SystemSummary[]> {
  const response = await fetchJSON<components['schemas']['SystemListResponse']>(
    `${API_BASE}/systems`,
  )
  return response.systems ?? []
}

/**
 * The repos some GitHub App installation can reach, by full name. This, not a
 * repo's own `installation_id`, is what tracks App access: CLI registration
 * leaves that field empty, and installation webhooks never update it.
 *
 * `complete` is false when GitHub failed for some installation, so a repo
 * missing from `names` may still be reachable.
 */
export interface AppAccess {
  names: string[]
  complete: boolean
}

export async function lookUpAppAccess(): Promise<AppAccess> {
  const response = await fetchJSON<components['schemas']['GitHubRepoListResponse']>(
    `${API_BASE}/github/repos`,
  )
  return {
    names: (response.repos ?? []).map((repo) => repo.full_name),
    complete: response.lookup === 'complete',
  }
}
