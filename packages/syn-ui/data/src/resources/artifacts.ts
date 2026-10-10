import { type ListQuery, bucketTimeWindow, listQueryParams, mapLimit, request, seg } from '../client'
import type { ArtifactListResponse, ArtifactResponse, ArtifactSummary } from '../types'
import { cached } from '../keys'

/** The narrowing the artifacts page applies on top of the shared list query. */
export interface ArtifactScope {
  workflow_id?: string
  phase_id?: string
  artifact_type?: string
  /** The run that wrote it; `/artifacts` filters on it. */
  execution_id?: string
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
  const q = bucketTimeWindow(query)
  return cached('listArtifacts', [q, scope], (s) => fetchArtifactPage(q, scope, s), { signal, staleAfter: 'list' })
}

/**
 * Each run's artifact total under the same filter (`/artifacts?execution_id=`,
 * one row a page, so only `total` is read). The list groups a page by run and
 * a group must count the run, not its share of the page.
 *
 * API gap: `/artifacts` has no per-execution facet, so this fans out, at most
 * four at a time, one cached request per run on the page.
 */
export async function countArtifactsByExecution(
  executionIds: readonly string[],
  query: Pick<ListQuery, 'q'> = {},
  scope: Pick<ArtifactScope, 'artifact_type'> = {},
  signal?: AbortSignal,
): Promise<Record<string, number>> {
  const ids = [...new Set(executionIds)]
  const totals = await mapLimit(ids, 4, async (id) => (await listArtifacts({ page: 1, page_size: 1, q: query.q }, { ...scope, execution_id: id }, signal)).total)
  return Object.fromEntries(ids.map((id, i) => [id, totals[i] ?? 0]))
}

async function fetchArtifactPage(query: ListQuery, scope: ArtifactScope, signal: AbortSignal): Promise<ArtifactPage> {
  const params = listQueryParams(query, 'created')
  // Artifacts have no status and `/artifacts` refuses `statuses` (#1313).
  params.delete('statuses')
  if (scope.workflow_id) params.set('workflow_id', scope.workflow_id)
  if (scope.phase_id) params.set('phase_id', scope.phase_id)
  if (scope.artifact_type) params.set('artifact_type', scope.artifact_type)
  if (scope.execution_id) params.set('execution_id', scope.execution_id)
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
