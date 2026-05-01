/**
 * URL-backed sort state for resource tables.
 *
 * Schema: `?sort=<key>&dir=<asc|desc>`. The configured default is never
 * written to the URL so a clean URL stays clean.
 *
 * Click a header to sort: same key flips direction, different key restarts at
 * the configured default direction (typically `desc` for numeric/time
 * columns).
 *
 * Generic over the page's sort-key union (e.g. SessionSortKey,
 * ExecutionSortKey) so each page gets compile-time-checked keys.
 */

import { useCallback, useMemo } from 'react'
import { useSearchParams } from 'react-router-dom'

export type SortDir = 'asc' | 'desc'

export interface SortState<K extends string = string> {
  key: K
  dir: SortDir
}

export interface SortConfig<K extends string> {
  validKeys: readonly K[]
  defaultKey: K
  defaultDir?: SortDir
}

export interface UseSortUrlStateResult<K extends string> {
  sort: SortState<K>
  toggleSort: (key: K) => void
  /** True iff the current sort differs from the configured default. */
  isDefault: boolean
  /** Restore the default key + direction (clears the URL params). */
  resetSort: () => void
}

// Legacy alias retained for SessionList during migration.
export type SortKey =
  | 'status'
  | 'workflow'
  | 'phase'
  | 'repos'
  | 'tokens'
  | 'cost'
  | 'duration'
  | 'started'

function parseKey<K extends string>(raw: string | null, config: SortConfig<K>): K {
  return (config.validKeys as readonly string[]).includes(raw ?? '')
    ? (raw as K)
    : config.defaultKey
}

function parseDir(raw: string | null): SortDir {
  return raw === 'asc' ? 'asc' : 'desc'
}

function withSort<K extends string>(
  prev: URLSearchParams,
  next: SortState<K>,
  config: SortConfig<K>,
): URLSearchParams {
  const out = new URLSearchParams(prev)
  const defaultDir = config.defaultDir ?? 'desc'
  if (next.key === config.defaultKey && next.dir === defaultDir) {
    out.delete('sort')
    out.delete('dir')
  } else {
    out.set('sort', next.key)
    out.set('dir', next.dir)
  }
  return out
}

function nextStateOnHeaderClick<K extends string>(
  prev: SortState<K>,
  key: K,
  defaultDir: SortDir,
): SortState<K> {
  if (prev.key !== key) return { key, dir: defaultDir }
  return { key, dir: prev.dir === 'desc' ? 'asc' : 'desc' }
}

export function useSortUrlState<K extends string>(
  config: SortConfig<K>,
): UseSortUrlStateResult<K> {
  const [searchParams, setSearchParams] = useSearchParams()
  const defaultDir = config.defaultDir ?? 'desc'

  const sort = useMemo<SortState<K>>(
    () => ({
      key: parseKey(searchParams.get('sort'), config),
      dir: parseDir(searchParams.get('dir')),
    }),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [searchParams, config.defaultKey],
  )

  const toggleSort = useCallback(
    (key: K) => {
      setSearchParams(
        (prev) => withSort(prev, nextStateOnHeaderClick(sort, key, defaultDir), config),
        { replace: true },
      )
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [sort, setSearchParams, config.defaultKey, defaultDir],
  )

  const resetSort = useCallback(() => {
    setSearchParams(
      (prev) => {
        const out = new URLSearchParams(prev)
        out.delete('sort')
        out.delete('dir')
        return out
      },
      { replace: true },
    )
  }, [setSearchParams])

  const isDefault = sort.key === config.defaultKey && sort.dir === defaultDir

  return { sort, toggleSort, isDefault, resetSort }
}
