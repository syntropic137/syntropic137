/**
 * Collects items and hands them over once per animation frame, so a burst of
 * live events causes one render, not one per event.
 */
export type Scheduler = (run: () => void) => () => void

/** requestAnimationFrame when there is one, otherwise a 16ms timer (Node, workers, hidden tabs keep working). */
export const frameScheduler: Scheduler = (run) => {
  if (typeof requestAnimationFrame === 'function') {
    const id = requestAnimationFrame(() => run())
    return () => cancelAnimationFrame(id)
  }
  const t = setTimeout(run, 16)
  return () => clearTimeout(t)
}

export interface FrameBatcher<T> {
  push(item: T): void
  /** Deliver anything pending now. */
  flush(): void
  /** Drop pending items and stop. */
  cancel(): void
  readonly pending: number
}

export function createFrameBatcher<T>(deliver: (items: T[]) => void, schedule: Scheduler = frameScheduler): FrameBatcher<T> {
  let queue: T[] = []
  let cancelScheduled: (() => void) | null = null

  const flush = () => {
    cancelScheduled?.()
    cancelScheduled = null
    if (queue.length === 0) return
    const items = queue
    queue = []
    deliver(items)
  }

  return {
    push(item) {
      queue.push(item)
      cancelScheduled ??= schedule(flush)
    },
    flush,
    cancel() {
      cancelScheduled?.()
      cancelScheduled = null
      queue = []
    },
    get pending() {
      return queue.length
    },
  }
}
