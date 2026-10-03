import type { components } from '../generated/api-types'
import { API_BASE, fetchJSON } from './base'

/**
 * Which optional features this deployment has switched on.
 *
 * Typed from the generated OpenAPI schema rather than hand-written, so a
 * field added or renamed on the API side fails `tsc` here instead of
 * silently reading `undefined` at runtime.
 */
export type Features = components['schemas']['FeaturesResponse']

export async function getFeatures(): Promise<Features> {
  return fetchJSON(`${API_BASE}/features`)
}
