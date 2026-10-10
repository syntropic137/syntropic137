/**
 * One shared ticking clock for anything on screen that reads "now": running
 * durations, "started 50m ago". Ticks once a second only while someone holds
 * it, so an idle app sets no timer. Reading `clock.now` inside a $derived
 * re-runs that derivation on every tick (feedback 5ed77fc5: durations froze
 * until a refresh).
 */
export class Clock {
  now = $state(Date.now())
  private holders = 0
  private timer: ReturnType<typeof setInterval> | null = null

  constructor(private readonly intervalMs = 1000) {}

  /** Keep the clock ticking until the returned function is called. */
  hold(): () => void {
    this.holders += 1
    if (!this.timer) {
      this.now = Date.now()
      this.timer = setInterval(() => (this.now = Date.now()), this.intervalMs)
    }
    let released = false
    return () => {
      if (released) return
      released = true
      this.holders -= 1
      if (this.holders === 0 && this.timer) {
        clearInterval(this.timer)
        this.timer = null
      }
    }
  }

  get ticking(): boolean {
    return this.timer !== null
  }
}

export const clock = new Clock()
