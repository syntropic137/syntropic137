import type { components } from '../generated/api-types'
import { API_BASE, fetchJSON } from './base'

export type Scorecard = components['schemas']['ScorecardResponse']
export type ScorecardTarget = components['schemas']['ScorecardTargetResponse']
export type ScorecardDailyPoint = components['schemas']['ScorecardDailyPointResponse']

/** The platform scorecard over the `window` UTC days ending now (`1d`..`30d`). */
export async function getScorecard(window = '7d'): Promise<Scorecard> {
  return fetchJSON<Scorecard>(`${API_BASE}/insights/scorecard?window=${encodeURIComponent(window)}`)
}
