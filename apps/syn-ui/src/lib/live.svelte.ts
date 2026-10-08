/**
 * App-wide live connection state for the shell's Live indicator.
 * Holds one activity-stream subscription for the app's lifetime.
 */
import type { LiveState } from '@syn137/skyline-core/patterns'
import { type StreamState, subscribeActivity } from '@syn137/syn-ui-data/live'

const toLive: Record<StreamState, LiveState> = { open: 'live', connecting: 'connecting', closed: 'offline', fixtures: 'fixtures' }

class Live {
  state = $state<LiveState>('connecting')
  private stop: (() => void) | null = null

  start(): () => void {
    this.stop ??= subscribeActivity({ onState: (s) => (this.state = toLive[s]) })
    return () => {
      this.stop?.()
      this.stop = null
    }
  }
}

export const live = new Live()
