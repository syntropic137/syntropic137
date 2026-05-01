/**
 * URL-backed sort state for the Sessions table.
 *
 * Schema: `?sort=cost&dir=desc`. The default (`started/desc`) is never written
 * to the URL so a clean URL stays clean.
 *
 * Click a header to sort: same key flips direction, different key restarts at
 * `desc` (most useful for cost / duration / started).
 */

import { useCallback, useMemo } from 'react'
import { useSearchParams } from 'react-router-dom'

export type SortKey =
  | 'status'
  | 'workflow'
  | 'phase'
  | 'repos'
  | 'tokens'
  | 'cost'
  | 'duration'
  | 'started'

export type SortDir = 'asc' | 'desc'

export interface SortState {
  key: SortKey
  dir: SortDir
}

const VALID_KEYS: SortKey[] = [
  'status',
  'workflow',
  'phase',
  'repos',
  'tokens',
  'cost',
  'duration',
  'started',
]

const DEFAULT_KEY: SortKey = 'started'
const DEFAULT_DIR: SortDir = 'desc'

function parseKey(raw: string | null): SortKey {
  return VALID_KEYS.includes(raw as SortKey) ? (raw as SortKey) : DEFAULT_KEY
}

function parseDir(raw: string | null): SortDir {
  return raw === 'asc' ? 'asc' : 'desc'
}

function withSort(prev: URLSearchParams, next: SortState): URLSearchParams {
  const out = new URLSearchParams(prev)
  if (next.key === DEFAULT_KEY && next.dir === DEFAULT_DIR) {
    out.delete('sort')
    out.delete('dir')
  } else {
    out.set('sort', next.key)
    out.set('dir', next.dir)
  }
  return out
}

function nextStateOnHeaderClick(prev: SortState, key: SortKey): SortState {
  if (prev.key !== key) return { key, dir: 'desc' }
  return { key, dir: prev.dir === 'desc' ? 'asc' : 'desc' }
}

export interface UseSortUrlStateResult {
  sort: SortState
  toggleSort: (key: SortKey) => void
}

export function useSortUrlState(): UseSortUrlStateResult {
  const [searchParams, setSearchParams] = useSearchParams()

  const sort = useMemo<SortState>(
    () => ({ key: parseKey(searchParams.get('sort')), dir: parseDir(searchParams.get('dir')) }),
    [searchParams],
  )

  const toggleSort = useCallback(
    (key: SortKey) => {
      setSearchParams((prev) => withSort(prev, nextStateOnHeaderClick(sort, key)), {
        replace: true,
      })
    },
    [sort, setSearchParams],
  )

  return { sort, toggleSort }
}
