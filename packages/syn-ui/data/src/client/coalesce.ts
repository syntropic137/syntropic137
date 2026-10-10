import { abortError } from './errors'

/**
 * Request coalescing: concurrent identical GETs share one network request.
 *
 * Each caller keeps its own AbortSignal. Aborting one caller rejects only
 * that caller; the shared request is aborted when every caller has gone.
 * The entry is dropped as soon as the request settles, so this is
 * de-duplication of in-flight work, not a cache.
 */
interface Flight<T> {
  promise: Promise<T>
  controller: AbortController
  waiters: number
}

/**
 * Identity a cache-managed load stamps on the signal it hands its fetcher: the
 * cache and its invalidation epoch (bumped by every invalidate and clear). The
 * transport adds it to its own coalescing key, so two keys asking for one URL
 * in one epoch share a request, and a request started before an invalidation is
 * never joined by a read after it.
 */
export const flightTags = new WeakMap<AbortSignal, string>()

export class Coalescer {
  private flights = new Map<string, Flight<unknown>>()

  get size(): number {
    return this.flights.size
  }

  run<T>(key: string, start: (signal: AbortSignal) => Promise<T>, signal?: AbortSignal): Promise<T> {
    if (signal?.aborted) return Promise.reject(abortError())
    const shared = this.flightFor(key, start)
    shared.waiters++
    if (!signal) return shared.promise
    return this.follow(key, shared, signal)
  }

  /** The in-flight request for `key`, starting one when there is none. */
  private flightFor<T>(key: string, start: (signal: AbortSignal) => Promise<T>): Flight<T> {
    const existing = this.flights.get(key) as Flight<T> | undefined
    if (existing) return existing
    const controller = new AbortController()
    const promise = start(controller.signal)
    const created: Flight<T> = { promise, controller, waiters: 0 }
    this.flights.set(key, created as Flight<unknown>)
    const clear = () => this.drop(key, created)
    promise.then(clear, clear)
    return created
  }

  private drop<T>(key: string, flight: Flight<T>): void {
    if (this.flights.get(key) === (flight as Flight<unknown>)) this.flights.delete(key)
  }

  /** One caller's view of a shared flight: settles with it, or rejects alone when its signal aborts. */
  private follow<T>(key: string, shared: Flight<T>, signal: AbortSignal): Promise<T> {
    return new Promise<T>((resolve, reject) => {
      let done = false
      const finish = (): boolean => {
        if (done) return false
        done = true
        return true
      }
      const onAbort = () => {
        if (!finish()) return
        this.leave(key, shared)
        reject(abortError())
      }
      const settle = (fn: () => void) => {
        if (!finish()) return
        signal.removeEventListener('abort', onAbort)
        fn()
      }
      signal.addEventListener('abort', onAbort, { once: true })
      shared.promise.then(
        (v) => settle(() => resolve(v)),
        (e: unknown) => settle(() => reject(e)),
      )
    })
  }

  /** A caller gives up; the shared request is aborted once nobody waits on it. */
  private leave<T>(key: string, shared: Flight<T>): void {
    shared.waiters--
    if (shared.waiters > 0) return
    shared.controller.abort()
    this.drop(key, shared)
  }
}

/**
 * Run `fn` over `items` with at most `limit` in flight; results keep input
 * order. For the few places a screen must fan out (prefer a list endpoint).
 */
export async function mapLimit<T, R>(items: readonly T[], limit: number, fn: (item: T, index: number) => Promise<R>): Promise<R[]> {
  const results = new Array<R>(items.length)
  let next = 0
  const worker = async () => {
    while (next < items.length) {
      const i = next++
      results[i] = await fn(items[i] as T, i)
    }
  }
  await Promise.all(Array.from({ length: Math.max(1, Math.min(limit, items.length)) }, worker))
  return results
}
