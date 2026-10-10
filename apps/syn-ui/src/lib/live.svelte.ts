/**
 * App-wide live connection state for the shell's Live indicator.
 * Holds one activity-stream subscription for the app's lifetime, and keeps
 * the query cache in step with it (live events invalidate cached reads). The
 * invalidation map is a lazy chunk: nothing on screen needs it before data has
 * loaded, so it stays out of the first load.
 */
import type { LiveState } from '@syn137/skyline-core/patterns'
import { type StreamState, subscribeActivity } from '@syn137/syn-ui-data/live'

const toLive: Record<StreamState, LiveState> = { open: 'live', connecting: 'connecting', closed: 'offline', fixtures: 'fixtures' }

class Live {
  state = $state<LiveState>('connecting')
  private stop: (() => void) | null = null

  start(): () => void {
    if (!this.stop) {
      const offState = subscribeActivity({ onState: (s) => (this.state = toLive[s]) })
      let offCache: (() => void) | null = null
      let stopped = false
      void import('@syn137/syn-ui-data/invalidate').then((m) => {
        if (!stopped) offCache = m.connectLiveInvalidation()
      })
      this.stop = () => {
        stopped = true
        offState()
        offCache?.()
      }
    }
    return () => {
      this.stop?.()
      this.stop = null
    }
  }
}

export const live = new Live()
