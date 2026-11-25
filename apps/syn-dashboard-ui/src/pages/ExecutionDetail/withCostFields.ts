/**
 * The execution detail with its cost fields filled in, read once at the page
 * boundary.
 *
 * An API that predates #897 / #2360 does not send the execution's
 * `total_cost_display`, `cost_by_model`, `cost_by_model_display` or
 * `unattributed_cost_display`. A newer dashboard in front of it (a rolling
 * deploy, a pinned gateway, a local UI against the VPS) used to throw on the
 * first `in` / `Object.keys` and render a blank page. Absent now means what it
 * meant before those fields existed: no split, no remainder, and no display
 * text for the total, which shows an em dash. Nothing is formatted here (#897).
 */

import type { components } from '../../generated/api-types'
import type { ExecutionDetailResponse } from '../../types'

type CostField = 'total_cost_display' | 'cost_by_model' | 'cost_by_model_display' | 'unattributed_cost_display'

export type ExecutionWithCost = Omit<ExecutionDetailResponse, CostField> &
  Pick<components['schemas']['ExecutionDetailResponse'], CostField>

const EM_DASH = '—'

export function withCostFields(execution: ExecutionDetailResponse): ExecutionWithCost {
  return {
    ...execution,
    total_cost_display: execution.total_cost_display ?? EM_DASH,
    cost_by_model: execution.cost_by_model ?? {},
    cost_by_model_display: execution.cost_by_model_display ?? {},
    unattributed_cost_display: execution.unattributed_cost_display ?? null,
  }
}
