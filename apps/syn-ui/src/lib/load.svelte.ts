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
 */
import { isAbortError } from '@syn137/syn-ui-data'
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

  $effect(() => {
    void version
    const controller = new AbortController()
    loading = true
    let promise: Promise<T>
    try {
      promise = fetcher(controller.signal)
    } catch (e) {
      promise = Promise.reject(e)
    }
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
    return () => controller.abort()
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
            version++
          } else if (!timer) {
            timer = setTimeout(() => {
              timer = undefined
              last = Date.now()
              version++
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
      version++
    },
  }
}
