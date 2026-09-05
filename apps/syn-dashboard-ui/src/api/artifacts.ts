import type { ArtifactListResponse, ArtifactResponse, ArtifactSummary } from '../types'
import { API_BASE, fetchJSON } from './base'
import { listQueryParams, type ListQuery } from './listQuery'

/** The narrowing the artifacts page applies on top of the shared list query. */
export interface ArtifactScope {
  workflow_id?: string
  phase_id?: string
  artifact_type?: string
}

/** One page of artifacts, and the numbers describing what it is a page of. */
export interface ArtifactPage {
  artifacts: ArtifactSummary[]
  /** Artifacts matching the query across every page - never `artifacts.length`. */
  total: number
  page: number
  page_size: number
  /** Matching artifacts tallied by type, over the collection, not the page. */
  type_counts: Record<string, number>
}

type ApiArtifactSummary = NonNullable<ArtifactListResponse['artifacts']>[number]

/** The generated row leaves nullable fields optional; the UI type requires them. */
function toArtifactSummary(row: ApiArtifactSummary): ArtifactSummary {
  return { ...row, title: row.title ?? null, created_at: row.created_at ?? null }
}

/**
 * One page of artifacts, with the total and type facets it was cut from.
 *
 * This used to return the rows alone, which is why nothing downstream could
 * tell a 50-row answer from a 50-row collection (#1204). The envelope is the
 * same one `/executions` and `/sessions` answer with, so it goes through the
 * same `listQueryParams`.
 */
export async function listArtifactPage(
  query: ListQuery,
  scope: ArtifactScope = {}
): Promise<ArtifactPage> {
  const params = listQueryParams(query, 'created')
  if (scope.workflow_id) params.set('workflow_id', scope.workflow_id)
  if (scope.phase_id) params.set('phase_id', scope.phase_id)
  if (scope.artifact_type) params.set('artifact_type', scope.artifact_type)
  const response = await fetchJSON<ArtifactListResponse>(`${API_BASE}/artifacts?${params}`)
  return {
    artifacts: (response.artifacts ?? []).map(toArtifactSummary),
    total: response.total,
    page: response.page,
    page_size: response.page_size,
    type_counts: response.type_counts ?? {},
  }
}

export async function getArtifact(
  artifactId: string,
  includeContent = false
): Promise<ArtifactResponse> {
  const query = includeContent ? '?include_content=true' : ''
  return fetchJSON(`${API_BASE}/artifacts/${artifactId}${query}`)
}

export async function getArtifactContent(
  artifactId: string
): Promise<{ artifact_id: string; content: string | null; content_type: string }> {
  return fetchJSON(`${API_BASE}/artifacts/${artifactId}/content`)
}
