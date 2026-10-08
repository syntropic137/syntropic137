/**
 * @syn137/syn-ui-data: the Skyline UI's API client. Plain TypeScript.
 *
 *   import { configureClient, listExecutions, getExecution } from '@syn137/syn-ui-data'
 *   import type { ExecutionDetailResponse } from '@syn137/syn-ui-data/types'
 *   import { subscribeActivity } from '@syn137/syn-ui-data/live'
 */
export * from './client'
export * from './resources/workflows'
export * from './resources/executions'
export * from './resources/sessions'
export * from './resources/sessionInventory'
export * from './resources/evals'
export * from './resources/artifacts'
export * from './resources/triggers'
export * from './resources/repos'
export * from './resources/costs'
export * from './resources/observability'
export * from './resources/insights'
export * from './resources/trends'
export { SSE_EVENTS } from './types'
export type * from './types'
export { subscribeActivity, subscribeExecution, liveHub } from './live'
export type { StreamState, StreamSubscriber } from './live'
