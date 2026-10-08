/**
 * Run history for the trend charts: GET /evals/{id}/trend and
 * GET /workflows/{id}/trend, one row per run, oldest first.
 *
 * TODO(#624): the endpoints are being built on the api-gaps branch. These
 * types are hand-written to that contract until they reach the OpenAPI spec;
 * then alias the generated schemas here. This file is the only adapter: the
 * screens read rows, never the response envelope.
 */
import { request, seg } from '../client'
import type { EvalVerdict } from './evals'

/** Marks a run made after its definition changed (change markers on the charts). */
export interface TrendDefinitionMark {
  definition_version?: string | null
  /** UTC ISO time the definition changed. */
  definition_changed_at?: string | null
}

export interface EvalTrendRow extends TrendDefinitionMark {
  /** UTC ISO start of the run. */
  date: string
  verifier_model: string
  judge_model: string | null
  /** Judge's quality score, 0 to 100; null until scored. */
  score: number | null
  verdict: EvalVerdict | null
  cost_usd: number
  duration_seconds: number | null
  tokens: number | null
  /** Not in the contract yet: lets the readout link to the run. */
  execution_id?: string | null
}

export interface WorkflowTrendPhase {
  phase_name: string
  duration_seconds: number | null
}

export interface WorkflowTrendRow extends TrendDefinitionMark {
  date: string
  status: string
  cost_usd: number
  duration_seconds: number | null
  tokens: number | null
  phase_durations: WorkflowTrendPhase[]
}

export interface EvalTrendResponse {
  eval_id: string
  rows: EvalTrendRow[]
}

export interface WorkflowTrendResponse {
  workflow_id: string
  rows: WorkflowTrendRow[]
}

export async function getEvalTrend(evalId: string, signal?: AbortSignal): Promise<EvalTrendRow[]> {
  const res = await request<EvalTrendResponse>(`/evals/${seg(evalId)}/trend`, { signal })
  return res.rows
}

export async function getWorkflowTrend(workflowId: string, signal?: AbortSignal): Promise<WorkflowTrendRow[]> {
  const res = await request<WorkflowTrendResponse>(`/workflows/${seg(workflowId)}/trend`, { signal })
  return res.rows
}
