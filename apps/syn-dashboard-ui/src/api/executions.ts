import type {
  ExecutionDetailResponse,
  ExecutionListResponse,
  WorkflowExecutionSummary,
} from '../types'
import { API_BASE, fetchJSON } from './base'

export async function listExecutions(
  workflowId: string,
  params?: { page?: number; page_size?: number }
): Promise<WorkflowExecutionSummary[]> {
  const searchParams = new URLSearchParams()
  if (params?.page) searchParams.set('page', String(params.page))
  if (params?.page_size) searchParams.set('page_size', String(params.page_size))

  const query = searchParams.toString()
  const response = await fetchJSON<{ runs: WorkflowExecutionSummary[] }>(
    `${API_BASE}/workflows/${workflowId}/runs${query ? `?${query}` : ''}`
  )
  return response.runs ?? []
}

// DEV ONLY: Session enrichment data from TimescaleDB agent_events, keyed by session_id.
// The Docker API image doesn't have cache token / model fields in its Pydantic model yet.
// TODO(#599): Remove once the API image is rebuilt with cache token + model response fields.
interface _DevSessionData {
  cache: [number, number]  // [cache_creation, cache_read]
  model: string
  costByModel: Record<string, string>
}
const _DEV_SESSION_DATA: Record<string, _DevSessionData> = {
  '38ff8ddd-d3b4-479f-a920-d0a98f6735c1': { cache: [50155, 316216], model: 'claude-sonnet-4-20250514', costByModel: { 'claude-sonnet-4-20250514': '0.0088' } },
  'b8d16aae-6d5c-41c5-8613-f68d3d88c5fa': { cache: [10273, 236663], model: 'claude-sonnet-4-20250514', costByModel: { 'claude-sonnet-4-20250514': '0.0022' } },
  '53d14951-d27c-4f5f-b596-181b6eb1ff82': { cache: [97572, 733069], model: 'claude-sonnet-4-20250514', costByModel: { 'claude-sonnet-4-20250514': '0.0070' } },
  'ed89e433-3b42-4c47-8236-25b36f801a33': { cache: [62893, 411030], model: 'claude-opus-4-20250514', costByModel: { 'claude-opus-4-20250514': '0.0051' } },
  '10d003d4-af3c-420d-84f2-0e921fc08fec': { cache: [20556, 317431], model: 'claude-sonnet-4-20250514', costByModel: { 'claude-sonnet-4-20250514': '0.0032' } },
  'd0175b9a-358d-4e97-9d44-cf1b1ca30183': { cache: [30954, 237153], model: 'claude-sonnet-4-20250514', costByModel: { 'claude-sonnet-4-20250514': '0.0028' } },
  '6e77090c-9903-40ab-8493-41765f882655': { cache: [33159, 226863], model: 'claude-haiku-4-5-20251001', costByModel: { 'claude-haiku-4-5-20251001': '0.0015' } },
  'd28c52a4-25ee-4763-9050-fbb14d97d3e5': { cache: [29968, 203407], model: 'claude-sonnet-4-20250514', costByModel: { 'claude-sonnet-4-20250514': '0.0024' } },
  'b0ef3842-55d6-44bc-9d61-e40b245167bf': { cache: [8932, 182633], model: 'claude-sonnet-4-20250514', costByModel: { 'claude-sonnet-4-20250514': '0.0019' } },
  // Research Workflow (exec-1f80ed1bcab3)
  '8053d0e6-e9a9-45aa-ac4d-beeb2cf2f8c8': { cache: [0, 0], model: 'claude-sonnet-4-20250514', costByModel: { 'claude-sonnet-4-20250514': '0.0003' } },
  '63d9a6bf-5788-473a-a84e-e7663d916554': { cache: [0, 0], model: 'claude-opus-4-20250514', costByModel: { 'claude-opus-4-20250514': '0.0004', 'claude-haiku-4-5-20251001': '0.0002' } },
  '38bcc2ae-b7be-4887-b274-31f2aefdcd43': { cache: [0, 0], model: 'claude-sonnet-4-20250514', costByModel: { 'claude-sonnet-4-20250514': '0.0003' } },
}

function _enrichPhase(phase: ExecutionDetailResponse['phases'][number], dev: _DevSessionData): void {
  if (!phase.cache_creation_tokens && !phase.cache_read_tokens) {
    phase.cache_creation_tokens = dev.cache[0]
    phase.cache_read_tokens = dev.cache[1]
  }
  if (!phase.model) phase.model = dev.model
  if (!phase.cost_by_model || Object.keys(phase.cost_by_model).length === 0) {
    phase.cost_by_model = dev.costByModel
  }
}

function _enrichSessionData(data: ExecutionDetailResponse): ExecutionDetailResponse {
  if (!data.phases) return data
  for (const phase of data.phases) {
    const dev = phase.session_id ? _DEV_SESSION_DATA[phase.session_id] : undefined
    if (dev) _enrichPhase(phase, dev)
  }
  if (!data.cache_creation_tokens) {
    data.cache_creation_tokens = data.phases.reduce((s, p) => s + (p.cache_creation_tokens ?? 0), 0)
  }
  if (!data.cache_read_tokens) {
    data.cache_read_tokens = data.phases.reduce((s, p) => s + (p.cache_read_tokens ?? 0), 0)
  }
  return data
}

export async function getExecution(executionId: string): Promise<ExecutionDetailResponse> {
  const data = await fetchJSON<ExecutionDetailResponse>(`${API_BASE}/executions/${executionId}`)
  return _enrichSessionData(data)
}

export async function listAllExecutions(params?: {
  status?: string
  page?: number
  page_size?: number
}): Promise<ExecutionListResponse> {
  const searchParams = new URLSearchParams()
  if (params?.status) searchParams.set('status', params.status)
  if (params?.page) searchParams.set('page', String(params.page))
  if (params?.page_size) searchParams.set('page_size', String(params.page_size))

  const query = searchParams.toString()
  return fetchJSON(`${API_BASE}/executions${query ? `?${query}` : ''}`)
}

export async function pauseExecution(
  executionId: string,
  reason?: string
): Promise<{ success: boolean; execution_id: string; state: string; message: string | null }> {
  return fetchJSON(`${API_BASE}/executions/${executionId}/pause`, {
    method: 'POST',
    body: JSON.stringify({ reason }),
  })
}

export async function resumeExecution(
  executionId: string
): Promise<{ success: boolean; execution_id: string; state: string; message: string | null }> {
  return fetchJSON(`${API_BASE}/executions/${executionId}/resume`, {
    method: 'POST',
  })
}

export async function cancelExecution(
  executionId: string,
  reason?: string
): Promise<{ success: boolean; execution_id: string; state: string; message: string | null }> {
  return fetchJSON(`${API_BASE}/executions/${executionId}/cancel`, {
    method: 'POST',
    body: JSON.stringify({ reason: reason ?? 'Cancelled from UI' }),
  })
}
