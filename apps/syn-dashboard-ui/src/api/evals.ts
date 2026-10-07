/**
 * Evals v2 read API: the eval list, one eval, and the runs of an eval.
 *
 * TODO(#1710): the response types below are hand-typed from the Evals v2
 * contract because the backend is being built in parallel and `just codegen`
 * does not have them yet. When it does, replace each interface with the
 * `components['schemas'][...]` alias of the same name. They are declared here
 * and nowhere else so that switch touches this one module.
 */

import { API_BASE, fetchJSON } from './base'

/** A scorer's judgement of one run. `ERROR` means the scorer could not judge. */
export type EvalVerdict = 'PASS' | 'FAIL' | 'ERROR'

export interface EvalBaselineRepo {
  repository: string
  requested_ref: string
  commit_sha: string
}

/** One (workflow, observed models) combination an eval has been run with. */
export interface EvalVariant {
  workflow_id: string
  /** Sorted, unique models the phases actually reported, never the alias asked for. */
  models: string[]
  run_count: number
  pass_count: number
  pass_rate: number | null
  pass_rate_display: string
  avg_cost_usd: number | null
  avg_cost_display: string
  last_run_at: string | null
}

export interface EvalSummary {
  eval_id: string
  name: string
  goal: string
  starting_workflow_id: string | null
  baseline_repos: EvalBaselineRepo[]
  tags: string[]
  frozen: boolean
  archived: boolean
  created_at: string | null
  updated_at: string | null
  run_count: number
  scored_count: number
  pass_rate: number | null
  pass_rate_display: string
  last_run_at: string | null
  last_verdict: EvalVerdict | null
  variants: EvalVariant[]
}

export interface EvalListResponse {
  evals: EvalSummary[]
  total: number
  page: number
  page_size: number
}

export interface EvalRunPhaseModel {
  phase_id: string
  model: string
}

/** One execution that is a member of an eval: one data point. */
export interface EvalRun {
  execution_id: string
  started_at: string | null
  completed_at: string | null
  status: string
  workflow_id: string
  /** Null until the backend can say which installed version a run used. */
  workflow_version: string | null
  models: EvalRunPhaseModel[]
  total_cost_usd: number | null
  total_cost_display: string
  duration_seconds: number | null
  duration_display: string
  verdict: EvalVerdict | null
  score: number | null
  evidence_excerpt: string | null
  scorer: string | null
  scored_at: string | null
}

export interface EvalRunListResponse {
  items: EvalRun[]
  total: number
  page: number
  page_size: number
}

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
