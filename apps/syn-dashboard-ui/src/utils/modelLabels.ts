import { REQUESTED_MODEL_PREFIX, UNATTRIBUTED_MODEL_KEY, UNATTRIBUTED_MODEL_LABEL } from '../constants/models'

/**
 * Label for a `cost_by_model` key.
 *
 * Keys are observed model ids and are shown verbatim - never shortened or
 * prettified - except the unattributed key, which reads as "unknown model".
 */
export function costByModelKeyLabel(key: string): string {
  return key === UNATTRIBUTED_MODEL_KEY ? UNATTRIBUTED_MODEL_LABEL : key
}

/**
 * Secondary "requested: <alias>" context, or null when it adds nothing.
 *
 * Only shown when a model WAS observed and differs from what was requested.
 * When nothing was observed the API's display string already carries
 * "unknown (requested: X)", so repeating it would be noise.
 */
export function requestedModelNote(
  observed: string | null | undefined,
  requested: string | null | undefined,
): string | null {
  if (!observed || !requested || requested === observed) return null
  return `${REQUESTED_MODEL_PREFIX}${requested}`
}
