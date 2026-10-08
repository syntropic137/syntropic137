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
  if (event.type === 'resize') {
    if (event.count <= 0) return { index: null, count: 0 }
    const keep = event.keep ?? null
    const index = keep !== null && keep >= 0 && keep < event.count ? keep : event.count - 1
    return { index, count: event.count }
  }
  if (count <= 0) return state
  const at = state.index ?? count - 1
  switch (event.type) {
    case 'prev':
      return { count, index: (at + count - 1) % count }
    case 'next':
      return { count, index: (at + 1) % count }
    case 'first':
      return { count, index: 0 }
    case 'last':
      return { count, index: count - 1 }
    case 'pick':
      return event.index >= 0 && event.index < count && event.index !== state.index ? { count, index: event.index } : state
  }
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
