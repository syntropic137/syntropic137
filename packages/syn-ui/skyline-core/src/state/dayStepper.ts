import type { Reducer } from './machine'

/**
 * Skyline day stepper: which active day the readout shows. Previous and next
 * wrap around, as on the Main board; pointing at a bar picks it directly.
 * `index` is null only when there are no active days.
 */
export interface DayStepperState {
  index: number | null
  count: number
}

export type DayStepperEvent =
  | { type: 'prev' }
  | { type: 'next' }
  | { type: 'first' }
  | { type: 'last' }
  | { type: 'pick'; index: number }
  /** The set of active days changed (new data, range toggle). Keeps the pick when it still exists, else selects the latest. */
  | { type: 'resize'; count: number; keep?: number | null }

/** Starts on the most recent active day. */
export function initialDayStepper(count: number): DayStepperState {
  return { index: count > 0 ? count - 1 : null, count }
}

export const dayStepper: Reducer<DayStepperState, DayStepperEvent> = (state, event) => {
  const { count } = state
  if (event.type === 'resize') return resizeStepper(event.count, event.keep ?? null)
  if (count <= 0) return state
  if (event.type === 'pick') return pickDay(state, event.index)
  return { count, index: STEP_TO[event.type](state.index ?? count - 1, count) }
}

/** Where each step lands from `at` among `count` days; prev and next wrap. */
const STEP_TO: Record<'prev' | 'next' | 'first' | 'last', (at: number, count: number) => number> = {
  prev: (at, count) => (at + count - 1) % count,
  next: (at, count) => (at + 1) % count,
  first: () => 0,
  last: (_at, count) => count - 1,
}

function resizeStepper(count: number, keep: number | null): DayStepperState {
  if (count <= 0) return { index: null, count: 0 }
  const index = keep !== null && keep >= 0 && keep < count ? keep : count - 1
  return { index, count }
}

function pickDay(state: DayStepperState, index: number): DayStepperState {
  const { count } = state
  return index >= 0 && index < count && index !== state.index ? { count, index } : state
}

/** "11 of 11 active days". */
export function stepperPosition(state: DayStepperState): string {
  if (state.index === null || state.count === 0) return 'No active days'
  return `${state.index + 1} of ${state.count} active ${state.count === 1 ? 'day' : 'days'}`
}

/** Keyboard keys a focused bar answers to (roving focus across active days). */
export function stepperKey(key: string): DayStepperEvent | null {
  switch (key) {
    case 'ArrowLeft':
    case 'ArrowUp':
      return { type: 'prev' }
    case 'ArrowRight':
    case 'ArrowDown':
      return { type: 'next' }
    case 'Home':
      return { type: 'first' }
    case 'End':
      return { type: 'last' }
    default:
      return null
  }
}
