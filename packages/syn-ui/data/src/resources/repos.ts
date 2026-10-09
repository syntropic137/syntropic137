import { request } from '../client'
import type { components } from '../generated/api-types'
import { cached } from '../keys'

export type RepoSummary = components['schemas']['RepoSummaryResponse']
export type SystemSummary = components['schemas']['SystemSummaryResponse']

/** Every repo registered with the platform, across organizations. */
export function listRepos(signal?: AbortSignal): Promise<RepoSummary[]> {
  return cached('listRepos', [], async (s) => {
    const response = await request<components['schemas']['RepoListResponse']>('/repos', { signal: s })
    return response.repos ?? []
  }, { signal, staleAfter: 'list' })
}

export function listSystems(signal?: AbortSignal): Promise<SystemSummary[]> {
  return cached('listSystems', [], async (s) => {
    const response = await request<components['schemas']['SystemListResponse']>('/systems', { signal: s })
    return response.systems ?? []
  }, { signal, staleAfter: 'list' })
}

/**
 * The repos some GitHub App installation can reach. `complete` is false when
 * GitHub failed for some installation, so a missing repo may still be reachable.
 */
export interface AppAccess {
  repos: { fullName: string; isPrivate: boolean }[]
  complete: boolean
}

export function lookUpAppAccess(signal?: AbortSignal): Promise<AppAccess> {
  return cached('lookUpAppAccess', [], async (s) => {
    const response = await request<components['schemas']['GitHubRepoListResponse']>('/github/repos', { signal: s })
    return {
      repos: (response.repos ?? []).map((repo) => ({ fullName: repo.full_name, isPrivate: repo.private })),
      complete: response.lookup === 'complete',
    }
  }, { signal, staleAfter: 'list' })
}
