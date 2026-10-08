import { request } from '../client'
import type { components } from '../generated/api-types'

export type RepoSummary = components['schemas']['RepoSummaryResponse']
export type SystemSummary = components['schemas']['SystemSummaryResponse']

/** Every repo registered with the platform, across organizations. */
export async function listRepos(signal?: AbortSignal): Promise<RepoSummary[]> {
  const response = await request<components['schemas']['RepoListResponse']>('/repos', { signal })
  return response.repos ?? []
}

export async function listSystems(signal?: AbortSignal): Promise<SystemSummary[]> {
  const response = await request<components['schemas']['SystemListResponse']>('/systems', { signal })
  return response.systems ?? []
}

/**
 * The repos some GitHub App installation can reach. `complete` is false when
 * GitHub failed for some installation, so a missing repo may still be reachable.
 */
export interface AppAccess {
  repos: { fullName: string; isPrivate: boolean }[]
  complete: boolean
}

export async function lookUpAppAccess(signal?: AbortSignal): Promise<AppAccess> {
  const response = await request<components['schemas']['GitHubRepoListResponse']>('/github/repos', { signal })
  return {
    repos: (response.repos ?? []).map((repo) => ({ fullName: repo.full_name, isPrivate: repo.private })),
    complete: response.lookup === 'complete',
  }
}
