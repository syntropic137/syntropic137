/**
 * State machines in skyline-core are plain reducers: `(state, event) => state`.
 * No timers, no DOM, no framework. A Svelte component holds the state in a
 * $state rune and dispatches events; side effects (timeouts, clipboard) live
 * in the component and report back as events.
 */
export type Reducer<S, E> = (state: S, event: E) => S

/** Fold a list of events through a reducer (handy in tests). */
export function run<S, E>(reducer: Reducer<S, E>, initial: S, events: readonly E[]): S {
  return events.reduce(reducer, initial)
}
