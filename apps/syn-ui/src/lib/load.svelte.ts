/**
 * resource(): the one data-loading pattern pages use.
 *
 *   <script lang="ts">
 *     import { getExecution } from '@syn137/syn-ui-data'
 *     import { resource } from '../../lib/load.svelte'
 *     let { params }: PageProps = $props()
 *     const exec = resource((signal) => getExecution(params.executionId, signal), {
 *       live: (type) => type.startsWith('phase_') || type.startsWith('workflow_'),
 *     })
 *   </script>
 *   {#if exec.error}...{:else if exec.data}...{:else}...{/if}
 *
 * - Call it during component init (it uses $effect).
 * - Reactive values read synchronously inside the fetcher (params, router.query,
 *   $state filters) are dependencies: changing one refetches and aborts the
 *   previous request. Read them BEFORE the first await.
 * - `data` keeps the previous value while refetching (no flash); `loading`
 *   says a request is in flight; `error` is the last failure (aborts ignored).
 * - `live` refetches (throttled, at most once per `liveIntervalMs`) when an
 *   activity-stream event passes the filter.
 * - Reads go through the data package's query cache (ADR-074): fresh data is
 *   served without a request, stale data is served at once and refreshed, and
 *   an invalidation of any key the fetcher read (live stream, mutation,
 *   `refresh()`) re-runs it. `track` records those keys while the fetcher
 *   runs synchronously, which is the same "before the first await" rule.
 * - A fetcher that returns a resource call directly (`(s) => getX(id, s)`)
 *   and hits the cache renders its data on the first frame: no skeleton when
 *   you come back to a page.
 */
import { untrack } from 'svelte'
import { isAbortError, queryCache } from '@syn137/syn-ui-data'
import { subscribeActivity } from '@syn137/syn-ui-data/live'

export interface Resource<T> {
  readonly data: T | undefined
  readonly error: unknown
  readonly loading: boolean
  /** Refetch now. */
  refresh(): void
}

export interface ResourceOptions {
  /** Refetch when an activity event of this type arrives. */
  live?: (eventType: string) => boolean
  /** Minimum gap between live refetches, ms (default 2000). */
  liveIntervalMs?: number
}

export function resource<T>(fetcher: (signal: AbortSignal) => Promise<T>, options: ResourceOptions = {}): Resource<T> {
  let data = $state<T | undefined>(undefined)
  let error = $state<unknown>(undefined)
  let loading = $state(true)
  let version = $state(0)
  // Cache keys the latest run read; plain (not reactive) on purpose.
  let keys: string[] = []
  const rerun = () => version++
  /** Make the latest run's reads stale (their listeners re-run us), or just re-run uncached fetchers. */
  const kick = () => {
    if (keys.length === 0) return rerun()
    for (const key of keys) queryCache.invalidate(key)
  }

  // First frame: run the fetcher once now; a cache hit seeds `data` before the
  // first render. The effect's own call below joins whatever this started.
  let seed: AbortController | null = new AbortController()
  try {
    const first = untrack(() => fetcher(seed!.signal))
    first.catch(() => {})
    const hit = queryCache.settled(first)
    if (hit) data = hit.value
  } catch {
    // the effect's run reports it
  }

  $effect(() => {
    void version
    const controller = new AbortController()
    loading = true
    let promise: Promise<T>
    try {
      const run = queryCache.track(() => fetcher(controller.signal))
      promise = run.value
      keys = run.keys
    } catch (e) {
      promise = Promise.reject(e)
      keys = []
    }
    seed?.abort()
    seed = null
    const unsubscribe = queryCache.subscribe(keys, rerun)
    promise.then(
      (value) => {
        if (controller.signal.aborted) return
        data = value
        error = undefined
        loading = false
      },
      (e: unknown) => {
        if (controller.signal.aborted || isAbortError(e)) return
        error = e
        loading = false
      },
    )
    return () => {
      unsubscribe()
      controller.abort()
    }
  })

  if (options.live) {
    const filter = options.live
    const gap = options.liveIntervalMs ?? 2000
    $effect(() => {
      let last = 0
      let timer: ReturnType<typeof setTimeout> | undefined
      const unsubscribe = subscribeActivity({
        filter,
        onFrames: () => {
          const wait = last + gap - Date.now()
          if (wait <= 0) {
            last = Date.now()
            kick()
          } else if (!timer) {
            timer = setTimeout(() => {
              timer = undefined
              last = Date.now()
              kick()
            }, wait)
          }
        },
      })
      return () => {
        clearTimeout(timer)
        unsubscribe()
      }
    })
  }

  return {
    get data() {
      return data
    },
    get error() {
      return error
    },
    get loading() {
      return loading
    },
    refresh() {
      kick()
    },
  }
}
