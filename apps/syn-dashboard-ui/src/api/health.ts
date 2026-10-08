import type { components } from '../generated/api-types'
import { API_BASE, fetchJSON } from './base'

/** `GET /health`: liveness plus the read-path block the rebuild banner reads. */
export type HealthResponse = components['schemas']['HealthResponse']

/** One read model's rebuild verdict, with display strings computed by the API. */
export type ReadModelStatus = components['schemas']['ReadModelStatus']

/** A projection held below an event it failed to apply (ESP #391). */
export type HeldProjectionHealth = components['schemas']['HeldProjectionHealth']

export async function getHealth(signal?: AbortSignal): Promise<HealthResponse> {
  return fetchJSON(`${API_BASE}/health`, { signal })
}
