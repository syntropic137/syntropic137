/**
 * Evals v2 read API. Every type is the generated schema of the response
 * model (#1710), so a renamed field fails the build instead of rendering
 * `undefined`.
 */
import { request, seg } from '../client'
import type { components } from '../generated/api-types'
import { cached } from '../keys'

type Schemas = components['schemas']

/** A scorer's judgement of one run. `ERROR` means the scorer could not judge. */
export type EvalVerdict = Schemas['Verdict']
export type EvalBaselineRepo = Schemas['EvalBaselineRepoResponse']
export type EvalVariant = Schemas['EvalVariantResponse']
export type EvalSummary = Schemas['EvalResponse']
export type EvalListResponse = Schemas['EvalListResponse']
export type EvalRunPhaseModel = Schemas['EvalRunModelResponse']
export type EvalRun = Schemas['EvalRunResponse']
export type EvalRunListResponse = Schemas['EvalRunListResponse']
export type ExecutionEvalRun = Schemas['ExecutionEvalRunResponse']

export function listEvals(params: { tag?: string; page?: number; page_size?: number } = {}, signal?: AbortSignal): Promise<EvalListResponse> {
  const query = { tag: params.tag, page: params.page && params.page > 1 ? params.page : undefined, page_size: params.page_size }
  return cached('listEvals', [query], (s) => request('/evals', { query, signal: s }), { signal, staleAfter: 'list' })
}

export function getEval(evalId: string, signal?: AbortSignal): Promise<EvalSummary> {
  return cached('getEval', [evalId], (s) => request(`/evals/${seg(evalId)}`, { signal: s }), { signal })
}

export function listEvalRuns(evalId: string, params: { page?: number; page_size?: number } = {}, signal?: AbortSignal): Promise<EvalRunListResponse> {
  return cached('listEvalRuns', [evalId, params], (s) => request(`/evals/${seg(evalId)}/runs`, { query: { ...params }, signal: s }), { signal, staleAfter: 'list' })
}
