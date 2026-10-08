/**
 * Eval fixtures typed by the generated Evals v2 response schemas (#1710).
 *
 * Display strings are deliberately ones the client could not compute from the
 * numbers beside them (`66.7% (2/3)` for 0.6667, `$0.41 est.` for 0.4123), so a
 * test passes only if the page prints the server's string verbatim.
 */

import type { EvalRun, EvalRunListResponse, EvalSummary, EvalVariant } from '../api/evals'

type EvalRunStats = EvalVariant['stats']

export function stats(overrides: Partial<EvalRunStats> = {}): EvalRunStats {
  return {
    median_duration_seconds: 1200,
    median_duration_display: '20m med.',
    incomplete_duration_count: 0,
    median_cost_usd: '0.4123',
    median_cost_display: '$0.41 med.',
    incomplete_cost_count: 1,
    cost_per_pass_usd: '0.6185',
    cost_per_pass_display: '>=$0.62 (partial)',
    pass_count: 2,
    fail_count: 1,
    error_count: 0,
    unscored_count: 0,
    ...overrides,
  }
}


export const LONG_MODEL = 'claude-opus-5-5-20261001-with-a-very-long-observed-model-identifier'

export function variant(overrides: Partial<EvalVariant> = {}): EvalVariant {
  return {
    workflow_id: 'wf-verifier',
    workflow_version: '1.4.0',
    models: ['claude-sonnet-5'],
    run_count: 3,
    pass_count: 2,
    pass_rate: 0.6667,
    pass_rate_display: '66.7% (2/3)',
    avg_cost_usd: '0.4123',
    avg_cost_display: '$0.41 est.',
    last_run_at: '2026-10-06T12:00:00Z',
    last_verdict: 'FAIL',
    stats: stats(),
    ...overrides,
  }
}

export function evalSummary(overrides: Partial<EvalSummary> = {}): EvalSummary {
  return {
    eval_id: 'eval-1',
    name: 'Fix the flaky checkout test',
    goal: 'Make tests/test_checkout.py pass reliably without skipping it.',
    starting_workflow_id: 'wf-verifier',
    baseline_repos: [
      { repository: 'acme/shop', requested_ref: 'main', commit_sha: '0123456789abcdef0123456789abcdef01234567' },
    ],
    tags: ['suite:verifier-seed'],
    frozen: true,
    archived: false,
    created_at: '2026-10-01T00:00:00Z',
    updated_at: '2026-10-01T00:00:00Z',
    run_count: 3,
    run_status_counts: { completed: 3 },
    scored_count: 3,
    pass_rate: 0.6667,
    pass_rate_display: '66.7% (2/3)',
    last_run_at: '2026-10-06T12:00:00Z',
    last_verdict: 'PASS',
    variants: [variant()],
    stats: stats({ median_duration_display: '18m all', median_cost_display: '$0.39 all', cost_per_pass_display: '$0.58 all' }),
    ...overrides,
  }
}

export function evalRun(overrides: Partial<EvalRun> = {}): EvalRun {
  return {
    execution_id: 'exec-1',
    started_at: '2026-10-06T12:00:00Z',
    completed_at: '2026-10-06T12:20:00Z',
    status: 'completed',
    workflow_id: 'wf-verifier',
    workflow_version: '1.4.0',
    models: [{ phase_id: 'implement', model: 'claude-sonnet-5' }],
    total_cost_usd: '0.4123',
    total_cost_display: '$0.41 est.',
    duration_seconds: 1200,
    duration_display: '20m 0s',
    verdict: 'PASS',
    score: 0.9,
    evidence_excerpt: 'All 14 checkout tests passed on 5 consecutive runs.',
    scorer: 'eval_suite',
    scorer_version: '2',
    scored_at: '2026-10-06T12:30:00Z',
    ...overrides,
  }
}

export function runPage(items: EvalRun[], total = items.length): EvalRunListResponse {
  return { items, total, page: 1, page_size: 50 }
}

export function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}
