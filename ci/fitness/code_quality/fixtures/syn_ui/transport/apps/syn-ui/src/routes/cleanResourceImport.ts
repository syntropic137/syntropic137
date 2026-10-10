// CLEAN: a route imports named resources and errors, which are not transport
import { ApiError, isAbortError, listExecutions, type ExecutionSummary } from '@syn137/syn-ui-data'
import { resource } from '../lib/load'
export const r = resource(() => listExecutions({}))
export const e = (x: unknown): x is ApiError => x instanceof ApiError || isAbortError(x)
export type S = ExecutionSummary
