/**
 * The query cache (ADR-074), keyed by resource name plus normalised params.
 * Fresh data is served without a request; stale data is served at once and
 * refreshed in the background, and the key's listeners hear when it lands.
 * Concurrent loads share one request (Coalescer; each signal cancels only its
 * caller). `invalidate` marks entries stale and notifies: the live stream
 * (live/invalidate.ts) and mutations use it. Fixtures mode never goes stale on
 * its own, so only invalidation refreshes; loads are still de-duplicated.
 * A binding uses `track` to learn the keys a fetcher read, then `subscribe`.
 */
import { Coalescer } from './coalesce'
import { clientConfig } from './config'

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
  /** Cancels this caller only. */
  signal?: AbortSignal
}

interface Entry extends QueryEntryInfo {
  data: unknown
  has: boolean
  fetchedAt: number
  staleAfter: number
  /** Bumped by invalidate; data is valid only when loaded at the current gen. */
  gen: number
  dataGen: number
}

export interface QueryCacheOptions {
  now?: () => number
  fixtures?: () => boolean
  /** Oldest unwatched entries are dropped past this many (default 300). */
  maxEntries?: number
}

/** Stable text for any JSON-ish value: object keys sorted, undefined dropped. */
function stable(value: unknown): string {
  if (value instanceof URLSearchParams) return JSON.stringify([...value].map(([k, v]) => `${k}=${v}`).sort())
  if (Array.isArray(value)) return `[${value.map(stable).join(',')}]`
  if (value && typeof value === 'object') {
    const obj = value as Record<string, unknown>
    const keys = Object.keys(obj).filter((k) => obj[k] !== undefined).sort()
    return `{${keys.map((k) => `${JSON.stringify(k)}:${stable(obj[k])}`).join(',')}}`
  }
  return value === undefined ? 'null' : JSON.stringify(value)
}

/** "getExecution" + ["abc"] -> 'getExecution:["abc"]'. */
export function queryKey(name: string, params: readonly unknown[]): string {
  return `${name}:${stable(params)}`
}

export class QueryCache {
  private entries = new Map<string, Entry>()
  private flights = new Coalescer()
  private listeners = new Map<string, Set<() => void>>()
  private collector: Set<string> | null = null

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
    if (!entry.has) return this.load(entry, fetcher, options.signal).then(structuredClone)
    if (this.isStale(entry)) this.load(entry, fetcher).catch(() => {}) // keep serving stale on failure
    return Promise.resolve(structuredClone(entry.data as T))
  }

  /** The cached value, fresh or stale, without loading or tracking. */
  peek<T>(name: string, params: readonly unknown[]): T | undefined {
    const entry = this.entries.get(queryKey(name, params))
    return entry?.has ? structuredClone(entry.data as T) : undefined
  }

  /** Mark matching entries stale and notify their listeners. Returns how many matched. */
  invalidate(match: QueryMatch): number {
    let count = 0
    for (const entry of [...this.entries.values()]) {
      if (typeof match === 'string' ? entry.key !== match : !match(entry)) continue
      entry.gen++
      count++
      this.emit(entry.key)
    }
    return count
  }

  /** Forget everything (tests, sign-out). Listeners stay registered. */
  clear(): void {
    this.entries.clear()
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
    if (entry.dataGen !== entry.gen) return true
    const fixtures = this.options.fixtures?.() ?? clientConfig().fixtures
    return !fixtures && this.now() - entry.fetchedAt >= entry.staleAfter
  }

  private entryFor(key: string, name: string, params: readonly unknown[]): Entry {
    const existing = this.entries.get(key)
    if (existing) return existing
    const entry: Entry = { key, name, params, data: undefined, has: false, fetchedAt: 0, staleAfter: 0, gen: 0, dataGen: -1 }
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

  /** One shared load per key and generation; a load started before an invalidation stays stale. */
  private load<T>(entry: Entry, fetcher: (signal: AbortSignal) => Promise<T>, signal?: AbortSignal): Promise<T> {
    const gen = entry.gen
    const start = (s: AbortSignal) =>
      fetcher(s).then((data) => {
        const refreshed = entry.has
        Object.assign(entry, { data, has: true, fetchedAt: this.now(), dataGen: gen })
        if (refreshed && this.entries.get(entry.key) === entry) this.emit(entry.key)
        return data
      })
    return this.flights.run(`${entry.key}#${gen}`, start, signal)
  }

  private emit(key: string): void {
    for (const listener of [...(this.listeners.get(key) ?? [])]) {
      try {
        listener()
      } catch {
        // one listener's error never blocks the others
      }
    }
  }
}

/** The tab-wide cache every resource reads through. */
export const queryCache = new QueryCache()
