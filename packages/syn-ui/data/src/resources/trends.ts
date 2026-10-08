/**
 * Run history for the trend charts: GET /evals/{id}/trend and
 * GET /workflows/{id}/trend (#1788, backend in PR #1800). Items come newest
 * first; the chart models sort by date themselves.
 *
 * TODO(#1788): hand-written to the PR #1800 response models
 * (EvalTrendResponse, WorkflowTrendResponse in syn_api/types.py) until they
 * reach this package's generated api-types.ts; then alias the schemas here.
 * This file is the only adapter between the API and the screens.
 */
import { request, seg } from '../client'
import type { EvalVerdict } from './evals'

/** Largest page the API serves (list_query.MAX_PAGE_SIZE). */
export const TREND_PAGE_SIZE = 200

export type DefinitionChangeKind = 'created' | 'updated' | 'phase_updated'

export interface DefinitionChange {
  definition_version: string | null
  /** ISO 8601 UTC. */
  changed_at: string
  kind: DefinitionChangeKind
}

/** Current definition, when it last changed, and every change (oldest first). */
export interface TrendDefinition {
  definition_version: string | null
  definition_changed_at: string | null
  definition_changes: DefinitionChange[]
}

interface TrendMoney {
  /** Decimal, sent as a string. */
  cost_usd: string | number | null
  cost_is_lower_bound: boolean
  cost_display: string
  duration_seconds: number | null
  duration_is_lower_bound: boolean
  duration_display: string
  tokens: number
}

export interface EvalTrendRow extends TrendMoney {
  execution_id: string
  /** Run start, ISO 8601 UTC; null if it never recorded one. */
  date: string | null
  workflow_id: string
  workflow_version: string | null
  eval_definition_version: string | null
  verifier_model: string | null
  observed_models: string[]
  /** Null for script-scored runs. */
  judge_model: string | null
  /** 0 to 100. */
  score: number | null
  verdict: EvalVerdict | null
}

export interface WorkflowTrendPhase {
  phase_id: string
  phase_name: string
  duration_seconds: number | null
}

export interface WorkflowTrendRow extends TrendMoney {
  execution_id: string
  date: string | null
  status: string
  workflow_version: string | null
  phase_durations: WorkflowTrendPhase[]
}

interface TrendPage<T> extends TrendDefinition {
  items: T[]
  total: number
  page: number
  page_size: number
}

export interface EvalTrendResponse extends TrendPage<EvalTrendRow> {
  eval_id: string
}

export interface WorkflowTrendResponse extends TrendPage<WorkflowTrendRow> {
  workflow_id: string
}

export function getEvalTrend(evalId: string, signal?: AbortSignal): Promise<EvalTrendResponse> {
  return request(`/evals/${seg(evalId)}/trend`, { query: { page_size: TREND_PAGE_SIZE }, signal })
}

export function getWorkflowTrend(workflowId: string, params: { page_size?: number } = {}, signal?: AbortSignal): Promise<WorkflowTrendResponse> {
  return request(`/workflows/${seg(workflowId)}/trend`, { query: { page_size: params.page_size ?? TREND_PAGE_SIZE }, signal })
}
