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

export class Coalescer {
  private flights = new Map<string, Flight<unknown>>()

  get size(): number {
    return this.flights.size
  }

  run<T>(key: string, start: (signal: AbortSignal) => Promise<T>, signal?: AbortSignal): Promise<T> {
    if (signal?.aborted) return Promise.reject(abortError())
    let flight = this.flights.get(key) as Flight<T> | undefined
    if (!flight) {
      const controller = new AbortController()
      const promise = start(controller.signal)
      const created: Flight<T> = { promise, controller, waiters: 0 }
      flight = created
      this.flights.set(key, created as Flight<unknown>)
      const clear = () => {
        if (this.flights.get(key) === (created as Flight<unknown>)) this.flights.delete(key)
      }
      promise.then(clear, clear)
    }
    const shared = flight
    shared.waiters++
    if (!signal) return shared.promise
    return new Promise<T>((resolve, reject) => {
      let done = false
      const onAbort = () => {
        if (done) return
        done = true
        shared.waiters--
        if (shared.waiters <= 0) {
          shared.controller.abort()
          if (this.flights.get(key) === (shared as Flight<unknown>)) this.flights.delete(key)
        }
        reject(abortError())
      }
      signal.addEventListener('abort', onAbort, { once: true })
      shared.promise.then(
        (v) => {
          if (done) return
          done = true
          signal.removeEventListener('abort', onAbort)
          resolve(v)
        },
        (e) => {
          if (done) return
          done = true
          signal.removeEventListener('abort', onAbort)
          reject(e)
        },
      )
    })
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
