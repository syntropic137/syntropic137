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
