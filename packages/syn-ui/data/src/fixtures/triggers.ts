import type { TriggerDetail, TriggerHistoryEntry } from '../resources/triggers'
import { RUNS } from './catalog'
import { type FixtureRoute, notFound, route } from './define'
import { DAY, HOUR, ago } from './seed'

const REPO = 'syntropic137/syntropic137'

export const TRIGGERS: TriggerDetail[] = [
  {
    trigger_id: 'trig-pr-review',
    name: 'Review every pull request',
    event: 'pull_request.opened',
    repository: REPO,
    workflow_id: 'pr-review',
    workflow_name: 'PR Review',
    status: 'active',
    fire_count: 42,
    conditions: { draft: false, base_branch: 'main' },
    installation_id: 'inst-1',
    input_mapping: { task: 'Review PR #{{pull_request.number}}' },
    config: { max_fires_per_day: 20, cooldown_seconds: 300 },
    created_by: 'neural',
  },
  {
    trigger_id: 'trig-ci-fix',
    name: 'Fix failing CI',
    event: 'check_run.completed',
    repository: REPO,
    workflow_id: 'research-workflow',
    workflow_name: 'Research Workflow',
    status: 'paused',
    fire_count: 6,
    conditions: { conclusion: 'failure' },
    installation_id: 'inst-1',
    input_mapping: { task: 'Investigate failing check {{check_run.name}}' },
    config: { max_fires_per_day: 5, cooldown_seconds: 900 },
    created_by: 'neural',
  },
]

const history = (t: TriggerDetail): TriggerHistoryEntry[] =>
  RUNS.filter((r) => r.workflowId === t.workflow_id)
    .slice(0, 6)
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
