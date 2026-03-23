import type { ArtifactResponse, ArtifactSummary } from '../types'
import { API_BASE, fetchJSON } from './base'

export async function listArtifacts(params?: {
  workflow_id?: string
  phase_id?: string
  artifact_type?: string
  limit?: number
}): Promise<ArtifactSummary[]> {
  const searchParams = new URLSearchParams()
  if (params?.workflow_id) searchParams.set('workflow_id', params.workflow_id)
  if (params?.phase_id) searchParams.set('phase_id', params.phase_id)
  if (params?.artifact_type) searchParams.set('artifact_type', params.artifact_type)
  if (params?.limit) searchParams.set('limit', String(params.limit))

  const query = searchParams.toString()
  return fetchJSON(`${API_BASE}/artifacts${query ? `?${query}` : ''}`)
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
