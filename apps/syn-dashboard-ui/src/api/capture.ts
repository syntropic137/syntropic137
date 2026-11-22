import type { components } from '../generated/api-types'
import { API_BASE, fetchJSON } from './base'

export type CaptureStatusResponse = components['schemas']['CaptureStatusResponse']
export type CaptureStatusEntry = components['schemas']['CaptureStatusEntry']

/** The session-capture verdicts recorded for one execution, newest first. */
export async function getExecutionCaptureStatus(
  executionId: string,
  signal?: AbortSignal
): Promise<CaptureStatusResponse> {
  const query = new URLSearchParams({ execution_id: executionId })
  return fetchJSON(`${API_BASE}/capture/status?${query}`, { signal })
}
