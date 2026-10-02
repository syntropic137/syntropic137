/**
 * Load one pinned inventory revision and classify the result into distinct,
 * user-visible states. Partial, unsupported and remote-disabled are properties
 * of a successful read (shown as notices), not failures.
 */
import { useEffect, useRef, useState } from 'react'

import { ApiError } from '../api/base'
import type { InventoryFilters } from '../api/sessionInventory'
import {
  DEFAULT_INVENTORY_BUDGET, continueSessionInventory, hasPending, loadSessionInventory, type InventoryData,
} from '../api/sessionInventoryTraversal'

export type SessionInventoryState =
  | { kind: 'loading' }
  | { kind: 'not_published'; data: InventoryData }
  | { kind: 'empty'; data: InventoryData }
  | { kind: 'ready'; data: InventoryData }
  | { kind: 'permission_denied'; message: string }
  | { kind: 'expired'; message: string }
  | { kind: 'error'; message: string }

export function classifyInventory(data: InventoryData): SessionInventoryState {
  if (!data.snapshot) return { kind: 'not_published', data }
  if (data.sections.node.length === 0 && !('node' in data.pending)) return { kind: 'empty', data }
  return { kind: 'ready', data }
}

export function classifyInventoryError(reason: unknown): SessionInventoryState {
  if (reason instanceof ApiError) {
    if (reason.status === 401 || reason.status === 403) return { kind: 'permission_denied', message: reason.message }
    if (reason.status === 410 || reason.code === 'cursor_expired') return { kind: 'expired', message: reason.message }
  }
  return { kind: 'error', message: reason instanceof Error ? reason.message : 'Unable to load session inventory' }
}

export interface UseSessionInventory {
  state: SessionInventoryState
  /** Re-read the head: a new revision may have been published. */
  reload: () => void
  /** Resume every truncated section of the same revision by one more budget. */
  loadMore: () => void
  loadingMore: boolean
}

type Settled = { request: string; state: SessionInventoryState }

function dataOf(state: SessionInventoryState): InventoryData | null {
  return state.kind === 'ready' || state.kind === 'empty' ? state.data : null
}

/** Publish a read's outcome for its request, unless that request was abandoned. */
function settle(
  read: Promise<InventoryData>, controller: AbortController, request: string, publish: (value: Settled) => void,
): Promise<void> {
  return read
    .then(data => { if (!controller.signal.aborted) publish({ request, state: classifyInventory(data) }) })
    .catch(reason => { if (!controller.signal.aborted) publish({ request, state: classifyInventoryError(reason) }) })
}

function canContinue(data: InventoryData | null, busy: boolean, controller: AbortController | null): data is InventoryData {
  return data !== null && hasPending(data) && !busy && controller !== null
}

export function useSessionInventory(
  executionId: string, filters: InventoryFilters, budget: number = DEFAULT_INVENTORY_BUDGET,
): UseSessionInventory {
  const [generation, setGeneration] = useState(0)
  const phase = filters.phase_id
  const attempt = filters.attempt_id
  // A result is shown only for the request that produced it; any newer request reads as loading.
  const request = JSON.stringify([executionId, phase ?? null, attempt ?? null, generation])
  const [settled, setSettled] = useState<Settled | null>(null)
  const [moreFor, setMoreFor] = useState<string | null>(null)
  const controllerRef = useRef<AbortController | null>(null)

  useEffect(() => {
    const controller = new AbortController()
    controllerRef.current = controller
    void settle(loadSessionInventory(executionId, { phase_id: phase, attempt_id: attempt }, controller.signal, budget), controller, request, setSettled)
    return () => controller.abort()
  }, [executionId, phase, attempt, request, budget])

  const state: SessionInventoryState = settled?.request === request ? settled.state : { kind: 'loading' }
  const loadingMore = moreFor === request

  function loadMore() {
    const data = dataOf(state)
    const controller = controllerRef.current
    if (!canContinue(data, loadingMore, controller) || !controller) return
    setMoreFor(request)
    void settle(continueSessionInventory(data, controller.signal, budget), controller, request, setSettled)
      .finally(() => { if (!controller.signal.aborted) setMoreFor(null) })
  }

  return { state, reload: () => setGeneration(value => value + 1), loadMore, loadingMore }
}
