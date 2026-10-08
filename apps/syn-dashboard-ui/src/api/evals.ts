/**
 * Evals v2 read API: the eval list, one eval, the runs of an eval, and the
 * eval an execution is a run of.
 *
 * Every type is the generated schema of the same response model (#1710), so a
 * renamed or retyped field in `apps/syn-api/src/syn_api/types.py` fails the
 * build here instead of rendering `undefined`.
 */

import type { components } from '../generated/api-types'
import { API_BASE, fetchJSON } from './base'

type Schemas = components['schemas']

/** A scorer's judgement of one run. `ERROR` means the scorer could not judge. */
export type EvalVerdict = Schemas['Verdict']

export type EvalBaselineRepo = Schemas['EvalBaselineRepoResponse']

/** One (workflow, workflow version, observed models) combination an eval has been run with. */
export type EvalVariant = Schemas['EvalVariantResponse']

export type EvalSummary = Schemas['EvalResponse']

export type EvalListResponse = Schemas['EvalListResponse']

export type EvalRunPhaseModel = Schemas['EvalRunModelResponse']

/** One execution that is a member of an eval: one data point. */
export type EvalRun = Schemas['EvalRunResponse']

export type EvalRunListResponse = Schemas['EvalRunListResponse']

/** The eval an execution is a current run of, and that run's verdict (`GET /executions/{id}`'s `eval`). */
export type ExecutionEvalRun = Schemas['ExecutionEvalRunResponse']

export async function listEvals(params: { tag?: string; page_size?: number } = {}): Promise<EvalListResponse> {
  const search = new URLSearchParams()
  if (params.tag) search.set('tag', params.tag)
  if (params.page_size) search.set('page_size', String(params.page_size))
  const query = search.toString()
  return fetchJSON(`${API_BASE}/evals${query ? `?${query}` : ''}`)
}

export async function getEval(evalId: string): Promise<EvalSummary> {
  return fetchJSON(`${API_BASE}/evals/${encodeURIComponent(evalId)}`)
}

export async function listEvalRuns(
  evalId: string,
  params: { page?: number; page_size?: number } = {},
): Promise<EvalRunListResponse> {
  const search = new URLSearchParams()
  if (params.page) search.set('page', String(params.page))
  if (params.page_size) search.set('page_size', String(params.page_size))
  const query = search.toString()
  return fetchJSON(`${API_BASE}/evals/${encodeURIComponent(evalId)}/runs${query ? `?${query}` : ''}`)
}
