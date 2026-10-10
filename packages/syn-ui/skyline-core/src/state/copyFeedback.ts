import type { Reducer } from './machine'

/**
 * Copy Button feedback: idle -> copying -> copied | failed -> idle.
 * The component starts a timer on `copied`/`failed` and sends `reset`
 * after COPY_FEEDBACK_MS.
 */
export type CopyState = 'idle' | 'copying' | 'copied' | 'failed'
export type CopyEvent = { type: 'copy' } | { type: 'success' } | { type: 'error' } | { type: 'reset' }

export const COPY_FEEDBACK_MS = 1600

export const copyFeedback: Reducer<CopyState, CopyEvent> = (state, event) => {
  switch (event.type) {
    case 'copy':
      return state === 'copying' ? state : 'copying'
    case 'success':
      return state === 'copying' ? 'copied' : state
    case 'error':
      return state === 'copying' ? 'failed' : state
    case 'reset':
      return 'idle'
  }
}
