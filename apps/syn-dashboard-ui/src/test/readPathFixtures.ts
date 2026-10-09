import type { HealthResponse, ReadModelStatus } from '../api'

/** Shaped like the API's verdict for workflow_executions 29,476 events into a 40,939-event replay. */
export const REBUILDING_EXECUTIONS: ReadModelStatus = {
  rebuilding: true,
  projection: 'workflow_executions',
  label_display: 'execution history',
  progress_pct: 28,
  progress_display: '28%',
  events_behind: 29476,
  events_behind_display: '29,476 events behind',
  summary_display: 'Rebuilding execution history - 28% (29,476 events behind).',
}

export function makeHealth(subscription: HealthResponse['subscription']): HealthResponse {
  return {
    status: 'healthy',
    mode: 'full',
    build: {
      version: '0.33.0',
      version_status: 'installed',
      image_tag: 'v0.33.0',
      commit: null,
      started_at: '2031-02-03T04:05:06Z',
      started_at_display: '2031-02-03 04:05 UTC',
    },
    subscription,
  }
}

export const HEALTHY = makeHealth({ status: 'healthy', held_projections: [], rebuilding_read_models: [] })

export const CATCHING_UP = makeHealth({
  status: 'catching_up',
  is_catching_up: true,
  held_projections: [],
  rebuilding_read_models: [REBUILDING_EXECUTIONS],
})
