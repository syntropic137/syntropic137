import type { ContributionHeatmapResult, OrgSummary, SystemSummary, RepoSummary } from '../types'

const BASE = '/api/v1'

async function fetchJSON<T>(path: string): Promise<T> {
  const res = await fetch(`${BASE}${path}`)
  if (!res.ok) {
    throw new Error(`API error: ${res.status} ${res.statusText}`)
  }
  return res.json() as Promise<T>
}

export async function getContributionHeatmap(params: {
  organization_id?: string
  system_id?: string
  repo_id?: string
  start_date?: string
  end_date?: string
  metric?: string
}): Promise<ContributionHeatmapResult> {
  const query = new URLSearchParams()
  for (const [k, v] of Object.entries(params)) {
    if (v) query.set(k, v)
  }
  const qs = query.toString()
  return fetchJSON(`/insights/contribution-heatmap${qs ? `?${qs}` : ''}`)
}

export async function listOrganizations(): Promise<OrgSummary[]> {
  const data = await fetchJSON<{ organizations: OrgSummary[] }>('/organizations')
  return data.organizations ?? []
}

export async function listSystems(organizationId?: string): Promise<SystemSummary[]> {
  const qs = organizationId ? `?organization_id=${organizationId}` : ''
  const data = await fetchJSON<{ systems: SystemSummary[] }>(`/systems${qs}`)
  return data.systems ?? []
}

export async function listRepos(systemId?: string): Promise<RepoSummary[]> {
  const qs = systemId ? `?system_id=${systemId}` : ''
  const data = await fetchJSON<{ repos: RepoSummary[] }>(`/repos${qs}`)
  return data.repos ?? []
}
