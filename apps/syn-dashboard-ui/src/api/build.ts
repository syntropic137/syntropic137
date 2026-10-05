import type { components } from '../generated/api-types'
import { API_BASE, fetchJSON } from './base'

/** Which build of the API is answering, and when it went live. */
export type BuildInfo = components['schemas']['BuildInfo']

export async function getBuildInfo(signal?: AbortSignal): Promise<BuildInfo> {
  return fetchJSON(`${API_BASE}/version`, { signal })
}
