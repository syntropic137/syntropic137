import type { TriggerDetail, TriggerHistoryEntry } from '../resources/triggers'
import { RUNS } from './catalog'
import { type FixtureRoute, notFound, route } from './define'
import { DAY, HOUR, ago } from './seed'

const REPO = 'syntropic137/syntropic137'

const SANDBOX = 'syntropic137/sandbox_syn-engineer-beta'

/** Self-heal mapping and config from the Triggers board. */
const CHECK_RUN_INPUTS = {
  branch: 'check_run.pull_requests[0].head.ref',
  pr_number: 'check_run.pull_requests[0].number',
  check_name: 'check_run.name',
  repository: 'repository.full_name',
  check_html_url: 'check_run.html_url',
  check_output_title: 'check_run.output.title',
  check_output_summary: 'check_run.output.summary',
}
const BOARD_CONFIG = { max_attempts: 3, daily_limit: 20, debounce_seconds: 0, cooldown_seconds: 300 }

const rulesFor = (repo: string, n: number, fired: [number, number, number], paused = false): TriggerDetail[] => [
  {
    trigger_id: `tr-5c9258b${n}`,
    name: 'Self-heal failing checks',
    event: 'check_run.completed',
    repository: repo,
    workflow_id: 'multi-agent',
    workflow_name: 'Multi-agent (claude plans, codex implements)',
    status: 'active',
    fire_count: fired[0],
    conditions: [
      { field: 'check_run.conclusion', operator: 'eq', value: 'failure' },
      { field: 'check_run.pull_requests', operator: 'not_empty' },
    ] as unknown as Record<string, unknown>,
    installation_id: 'inst-1',
    input_mapping: CHECK_RUN_INPUTS,
    config: BOARD_CONFIG,
    created_by: 'neural',
  },
  {
    trigger_id: `tr-a17e40c${n}`,
    name: 'Review requested changes',
    event: 'pull_request_review.submitted',
    repository: repo,
    workflow_id: 'pr-review',
    workflow_name: 'PR Review',
    status: paused ? 'paused' : 'active',
    fire_count: fired[1],
    conditions: [{ field: 'review.state', operator: 'eq', value: 'changes_requested' }] as unknown as Record<string, unknown>,
    installation_id: 'inst-1',
    input_mapping: { pr_number: 'pull_request.number', review_body: 'review.body', repository: 'repository.full_name' },
    config: { max_attempts: 2, daily_limit: 10, debounce_seconds: 60, cooldown_seconds: 600 },
    created_by: 'neural',
  },
  {
    trigger_id: `tr-0d3bf91${n}`,
    name: 'Research on /research comment',
    event: 'issue_comment.created',
    repository: repo,
    workflow_id: 'research-workflow',
    workflow_name: 'Research Workflow',
    status: 'active',
    fire_count: fired[2],
    conditions: { 'comment.body': '/research' },
    installation_id: 'inst-1',
    input_mapping: { topic: 'comment.body', issue_number: 'issue.number' },
    config: { daily_limit: 5, cooldown_seconds: 900 },
    created_by: 'neural',
  },
]

export const TRIGGERS: TriggerDetail[] = [...rulesFor(REPO, 1, [0, 12, 4]), ...rulesFor(SANDBOX, 2, [3, 0, 0], true)]

const history = (t: TriggerDetail): TriggerHistoryEntry[] =>
  RUNS.filter((r) => r.workflowId === t.workflow_id)
    .slice(0, Math.min(6, t.fire_count))
    .map((r, i) => ({
      fired_at: ago(i * DAY + 2 * HOUR),
      execution_id: r.id,
      webhook_delivery_id: `delivery-${i}`,
      event_type: t.event,
      pr_number: 1400 + i,
      status: r.status,
      cost_usd: r.cost,
      trigger_id: t.trigger_id,
    }))

const find = (id: string) => TRIGGERS.find((t) => t.trigger_id === id) ?? notFound('Trigger')

export const triggerRoutes: FixtureRoute[] = [
  route('GET', '/triggers', ({ query }) => {
    const status = query.get('status')
    const repository = query.get('repository')
    const triggers = TRIGGERS.filter((t) => (!status || t.status === status) && (!repository || t.repository === repository)).map(
      ({ conditions: _c, installation_id: _i, input_mapping: _m, config: _cfg, created_by: _b, ...summary }) => summary,
    )
    return { triggers, total: triggers.length }
  }),
  route('GET', '/triggers/:triggerId', ({ params }) => find(params.triggerId!)),
  route('GET', '/triggers/:triggerId/history', ({ params }) => {
    const t = find(params.triggerId!)
    return { trigger_id: t.trigger_id, entries: history(t) }
  }),
  route('PATCH', '/triggers/:triggerId', ({ params, body }) => {
    const t = find(params.triggerId!)
    const action = (body as { action?: string } | null)?.action === 'pause' ? 'pause' : 'resume'
    t.status = action === 'pause' ? 'paused' : 'active'
    return { trigger_id: t.trigger_id, status: t.status, action }
  }),
  route('DELETE', '/triggers/:triggerId', ({ params }) => {
    const t = find(params.triggerId!)
    TRIGGERS.splice(TRIGGERS.indexOf(t), 1)
    return { trigger_id: t.trigger_id, status: 'deleted' }
  }),
]
