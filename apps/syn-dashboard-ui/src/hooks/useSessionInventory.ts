/**
 * Load one pinned inventory revision and classify the result into distinct,
 * user-visible states. Partial, unsupported and remote-disabled are properties
 * of a successful read (shown as notices), not failures.
 */
import { useEffect, useState } from 'react'

import { ApiError } from '../api/base'
import type { InventoryFilters } from '../api/sessionInventory'
import { loadSessionInventory, type InventoryData } from '../api/sessionInventoryTraversal'

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
  if (data.sections.node.length === 0) return { kind: 'empty', data }
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
}

export function useSessionInventory(executionId: string, filters: InventoryFilters): UseSessionInventory {
  const [generation, setGeneration] = useState(0)
  const phase = filters.phase_id
  const attempt = filters.attempt_id
  // A result is shown only for the request that produced it; any newer request reads as loading.
  const request = JSON.stringify([executionId, phase ?? null, attempt ?? null, generation])
  const [settled, setSettled] = useState<{ request: string; state: SessionInventoryState } | null>(null)

  useEffect(() => {
    const controller = new AbortController()
    loadSessionInventory(executionId, { phase_id: phase, attempt_id: attempt }, controller.signal)
      .then(data => { if (!controller.signal.aborted) setSettled({ request, state: classifyInventory(data) }) })
      .catch(reason => { if (!controller.signal.aborted) setSettled({ request, state: classifyInventoryError(reason) }) })
    return () => controller.abort()
  }, [executionId, phase, attempt, request])

  const state: SessionInventoryState = settled?.request === request ? settled.state : { kind: 'loading' }
  return { state, reload: () => setGeneration(value => value + 1) }
}
