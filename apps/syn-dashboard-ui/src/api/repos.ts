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
 * Full names of every repo some GitHub App installation can reach. This, not a
 * repo's own `installation_id`, is what tracks App access: CLI registration
 * leaves that field empty, and installation webhooks never update it.
 */
export async function listAppAccessibleRepoNames(): Promise<string[]> {
  const response = await fetchJSON<components['schemas']['GitHubRepoListResponse']>(
    `${API_BASE}/github/repos`,
  )
  return (response.repos ?? []).map((repo) => repo.full_name)
}
