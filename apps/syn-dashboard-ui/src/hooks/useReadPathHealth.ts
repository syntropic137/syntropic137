/**
 * Whether the read models behind this dashboard are rebuilding or stuck.
 *
 * After a deploy bumps a projection's version, its read model replays history
 * and serves a partial view for minutes: the execution list shows part of
 * history and the newest runs are missing, which looks broken. This hook reads
 * `/health` so the shell can say why. Every judgement is the API's - which
 * read models are rebuilding (ordinary live lag excluded), how far along, and
 * the words to show - so nothing here computes a percentage.
 *
 * It asks once on mount, then polls only while there is something to show,
 * and stops as soon as the read path is healthy again. A failed fetch keeps
 * the last answer.
 */

import { createContext, useCallback, useContext, useEffect, useState } from 'react'

import { getHealth, type HealthResponse, type HeldProjectionHealth, type ReadModelStatus } from '../api'
import { ifStillWanted } from './serialRefreshLoop'
import { useSerialRefresh } from './useSerialRefresh'

/** How often to re-read `/health` while a rebuild or a hold is on screen. */
export const READ_PATH_POLL_INTERVAL_MS = 10_000

export interface ReadPathHealth {
  /** Read models replaying history, furthest behind first. */
  rebuilding: ReadModelStatus[]
  /** Projections held below an event they failed to apply. */
  held: HeldProjectionHealth[]
  /** Global nonce of the undecodable event the subscription halted at, or null. */
  haltedAt: number | null
}

export const HEALTHY_READ_PATH: ReadPathHealth = { rebuilding: [], held: [], haltedAt: null }

export function readPathHealthOf(health: HealthResponse | null): ReadPathHealth {
  const sub = health?.subscription
  if (!sub) return HEALTHY_READ_PATH
  return {
    rebuilding: sub.rebuilding_read_models ?? [],
    held: sub.held_projections ?? [],
    haltedAt: sub.halted_at ?? null,
  }
}

/** True when anything is on screen that a later answer could clear. */
export function readPathNeedsWatching(health: ReadPathHealth): boolean {
  return health.rebuilding.length > 0 || health.held.length > 0 || health.haltedAt !== null
}

export function useReadPathHealth(): ReadPathHealth {
  const [health, setHealth] = useState<HealthResponse | null>(null)

  const fetchHealth = useCallback(
    (signal: AbortSignal): Promise<void> => getHealth(signal).then(ifStillWanted(signal, setHealth)),
    [],
  )

  const readPath = readPathHealthOf(health)
  const { refetch } = useSerialRefresh({
    fetch: fetchHealth,
    pollIntervalMs: readPathNeedsWatching(readPath) ? READ_PATH_POLL_INTERVAL_MS : null,
  })

  useEffect(() => {
    refetch()
  }, [refetch])

  return readPath
}

/** The shell's answer, shared with pages so they do not poll `/health` again. */
export const ReadPathHealthContext = createContext<ReadPathHealth>(HEALTHY_READ_PATH)

/** This page's read model, if it is rebuilding right now. */
export function useRebuildingReadModel(projection: string): ReadModelStatus | null {
  const { rebuilding } = useContext(ReadPathHealthContext)
  return rebuilding.find((status) => status.projection === projection) ?? null
}
