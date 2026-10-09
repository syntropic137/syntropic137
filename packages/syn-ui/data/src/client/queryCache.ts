/**
 * The query cache (ADR-074), keyed by resource name plus params (queryKey.ts).
 * Fresh data is served without a request. Time-stale data is served at once
 * and refreshed in the background (a failed background refresh keeps the old
 * data). Invalidated data is different: the next read waits for the refresh,
 * so a failure rejects that read and the binding shows it. Concurrent loads of
 * one key and generation share one load (Coalescer; each signal cancels only
 * its caller), and loads of different keys share one HTTP request for the same
 * URL within one invalidation epoch; a load publishes only if it was not abandoned, its generation is
 * still current and its entry is still the cached one. Fixtures mode never goes
 * stale by time. Bindings `track` a fetcher's keys, then `subscribe`.
 */
import { Coalescer, flightTags } from './coalesce'
import { clientConfig } from './config'
import { queryKey, snapshotParams } from './queryKey'

export { queryKey }

/** Default staleness by resource shape, ms. */
export const STALE_AFTER = { list: 15_000, detail: 60_000, metrics: 5_000 } as const
export type StaleKind = keyof typeof STALE_AFTER

/** What a predicate sees of an entry. */
export interface QueryEntryInfo {
  readonly key: string
  readonly name: string
  readonly params: readonly unknown[]
}
export type QueryMatch = string | ((entry: QueryEntryInfo) => boolean)

export interface QueryGetOptions {
  /** ms, or a shape whose default applies. Default 'detail'. */
  staleAfter?: number | StaleKind
  signal?: AbortSignal // cancels this caller only
}

/** A value `get` can show before its promise settles. `invalidated`: a refresh is pending and may still fail. */
export interface SettledValue<T> {
  value: T
  invalidated: boolean
}

interface Entry extends QueryEntryInfo {
  data: unknown
  fetchedAt: number
  staleAfter: number
  gen: number // cache-wide counter, new on create and invalidate; data is fresh only if loaded at the current gen
  dataGen: number // -1 until the first load lands
}

export interface QueryCacheOptions {
  now?: () => number
  fixtures?: () => boolean
  maxEntries?: number // oldest unwatched entries go past this (default 300)
}

let cacheIds = 0

export class QueryCache {
  private entries = new Map<string, Entry>()
  private flights = new Coalescer()
  private listeners = new Map<string, Set<() => void>>()
  private collector: Set<string> | null = null
  private gens = 0
  // Bumped by every invalidate() and clear(): HTTP sharing never crosses one (see load).
  private epoch = 0
  private readonly id = ++cacheIds
  private served = new WeakMap<Promise<unknown>, SettledValue<unknown>>()

  constructor(private readonly options: QueryCacheOptions = {}) {}

  get size(): number {
    return this.entries.size
  }

  /** Cached data when fresh, stale data plus a background refresh, or a (shared) load. */
  get<T>(name: string, params: readonly unknown[], fetcher: (signal: AbortSignal) => Promise<T>, options: QueryGetOptions = {}): Promise<T> {
    const key = queryKey(name, params)
    this.collector?.add(key)
    const entry = this.entryFor(key, name, params)
    const stale = options.staleAfter ?? 'detail'
    entry.staleAfter = typeof stale === 'number' ? stale : STALE_AFTER[stale]
    // Every caller gets its own copy, so a screen editing a response never edits the cache.
    if (entry.dataGen < 0) return this.load(entry, fetcher, options.signal).then((data) => structuredClone(data))
    if (entry.dataGen !== entry.gen) {
      // Invalidated: wait for the refresh so its failure reaches the caller; meanwhile `settled` offers the old value.
      const refresh = this.load(entry, fetcher, options.signal).then((data) => structuredClone(data))
      this.served.set(refresh, { value: structuredClone(entry.data), invalidated: true })
      return refresh
    }
    if (this.isStale(entry)) this.load(entry, fetcher).catch(() => {}) // time-stale: keep serving on failure
    const value = structuredClone(entry.data as T)
    const served = Promise.resolve(value)
    this.served.set(served, { value, invalidated: false })
    return served
  }

  /** The value `get` offered for a promise, readable synchronously (no first-render flash). */
  settled<T>(promise: Promise<T>): SettledValue<T> | undefined {
    return this.served.get(promise) as SettledValue<T> | undefined
  }

  /** The cached value, fresh or stale, without loading or tracking. */
  peek<T>(name: string, params: readonly unknown[]): T | undefined {
    const entry = this.entries.get(queryKey(name, params))
    return entry && entry.dataGen >= 0 ? structuredClone(entry.data as T) : undefined
  }

  /** Mark matching entries stale and notify their listeners. Returns how many matched. */
  invalidate(match: QueryMatch): number {
    let count = 0
    for (const entry of [...this.entries.values()]) {
      if (typeof match === 'string' ? entry.key !== match : !match(entry)) continue
      entry.gen = ++this.gens
      count++
      this.emit(entry.key)
    }
    if (count > 0) this.epoch++
    return count
  }

  /** Forget everything (tests, sign-out). Listeners stay registered. */
  clear(): void {
    this.entries.clear()
    this.epoch++
  }

  /** Hear when any of `keys` is refreshed or invalidated. */
  subscribe(keys: Iterable<string>, listener: () => void): () => void {
    const list = [...keys]
    for (const key of list) {
      let set = this.listeners.get(key)
      if (!set) this.listeners.set(key, (set = new Set()))
      set.add(listener)
    }
    return () => {
      for (const key of list) {
        const set = this.listeners.get(key)
        set?.delete(listener)
        if (set?.size === 0) this.listeners.delete(key)
      }
    }
  }

  /** Run `fn` and report the keys it read synchronously (before its first await). */
  track<T>(fn: () => T): { value: T; keys: string[] } {
    const outer = this.collector
    const keys = new Set<string>()
    this.collector = keys
    try {
      return { value: fn(), keys: [...keys] }
    } finally {
      this.collector = outer
      if (outer) for (const k of keys) outer.add(k)
    }
  }

  private now(): number {
    return this.options.now?.() ?? Date.now()
  }

  private isStale(entry: Entry): boolean {
    const fixtures = this.options.fixtures?.() ?? clientConfig().fixtures
    return !fixtures && this.now() - entry.fetchedAt >= entry.staleAfter
  }

  private entryFor(key: string, name: string, params: readonly unknown[]): Entry {
    const existing = this.entries.get(key)
    if (existing) return existing
    const entry: Entry = { key, name, params: snapshotParams(params), data: undefined, fetchedAt: 0, staleAfter: 0, gen: ++this.gens, dataGen: -1 }
    this.entries.set(key, entry)
    this.evict()
    return entry
  }

  private evict(): void {
    const max = this.options.maxEntries ?? 300
    for (const key of this.entries.keys()) {
      if (this.entries.size <= max) return
      if (!this.listeners.has(key)) this.entries.delete(key)
    }
  }

  /** One shared load per key and generation; publishes only if not abandoned, still current, still cached. */
  private load<T>(entry: Entry, fetcher: (signal: AbortSignal) => Promise<T>, signal?: AbortSignal): Promise<T> {
    const gen = entry.gen
    const flight = `${entry.key}#${gen}`
    const start = (s: AbortSignal) => {
      // The transport joins identical URLs only within one epoch, across keys: a request
      // started before any invalidation is never joined by a load started after it.
      flightTags.set(s, `${this.id}:${this.epoch}`)
      return fetcher(s).then((data) => {
        if (s.aborted || gen !== entry.gen || this.entries.get(entry.key) !== entry) return data
        const refreshed = entry.dataGen >= 0
        Object.assign(entry, { data: structuredClone(data), fetchedAt: this.now(), dataGen: gen })
        if (refreshed) this.emit(entry.key)
        return data
      })
    }
    return this.flights.run(flight, start, signal)
  }

  private emit(key: string): void {
    for (const listener of [...(this.listeners.get(key) ?? [])]) {
      try {
        listener()
      } catch {} // one listener's error never blocks the others
    }
  }
}

/** The tab-wide cache every resource reads through. */
export const queryCache = new QueryCache()
