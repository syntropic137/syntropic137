import { type ListQuery, listQueryParams, request, seg } from '../client'
import type { ArtifactListResponse, ArtifactResponse, ArtifactSummary } from '../types'
import { cached } from '../keys'

/** The narrowing the artifacts page applies on top of the shared list query. */
export interface ArtifactScope {
  workflow_id?: string
  phase_id?: string
  artifact_type?: string
}

/** One page of artifacts with the total and type facets it was cut from (#1204). */
export interface ArtifactPage extends Omit<ArtifactListResponse, 'artifacts' | 'type_counts'> {
  artifacts: ArtifactSummary[]
  type_counts: Record<string, number>
}

type ApiArtifactSummary = NonNullable<ArtifactListResponse['artifacts']>[number]

function toArtifactSummary(row: ApiArtifactSummary): ArtifactSummary {
  return { ...row, title: row.title ?? null, created_at: row.created_at ?? null }
}

export function listArtifacts(query: ListQuery, scope: ArtifactScope = {}, signal?: AbortSignal): Promise<ArtifactPage> {
  return cached('listArtifacts', [query, scope], (s) => fetchArtifactPage(query, scope, s), { signal, staleAfter: 'list' })
}

async function fetchArtifactPage(query: ListQuery, scope: ArtifactScope, signal: AbortSignal): Promise<ArtifactPage> {
  const params = listQueryParams(query, 'created')
  // Artifacts have no status and `/artifacts` refuses `statuses` (#1313).
  params.delete('statuses')
  if (scope.workflow_id) params.set('workflow_id', scope.workflow_id)
  if (scope.phase_id) params.set('phase_id', scope.phase_id)
  if (scope.artifact_type) params.set('artifact_type', scope.artifact_type)
  const response = await request<ArtifactListResponse>('/artifacts', { query: params, signal })
  return {
    ...response,
    artifacts: (response.artifacts ?? []).map(toArtifactSummary),
    type_counts: response.type_counts ?? {},
  }
}

export function getArtifact(artifactId: string, includeContent = false, signal?: AbortSignal): Promise<ArtifactResponse> {
  return cached('getArtifact', [artifactId, includeContent], (s) =>
    request(`/artifacts/${seg(artifactId)}`, { query: { include_content: includeContent || undefined }, signal: s }), { signal })
}

export interface ArtifactContent {
  artifact_id: string
  content: string | null
  content_type: string
}

export function getArtifactContent(artifactId: string, signal?: AbortSignal): Promise<ArtifactContent> {
  return cached('getArtifactContent', [artifactId], (s) => request(`/artifacts/${seg(artifactId)}/content`, { signal: s }), { signal })
}
