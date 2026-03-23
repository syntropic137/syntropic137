import { useEffect, useState } from 'react'

/**
 * Returns a `now` timestamp (Date.now()) that updates every `intervalMs`
 * while `enabled` is true. Useful for live duration displays.
 */
export function useLiveTimer(enabled: boolean, intervalMs = 1000): number {
  const [now, setNow] = useState(() => Date.now())

  useEffect(() => {
    if (!enabled) return

    const id = setInterval(() => setNow(Date.now()), intervalMs)
    return () => clearInterval(id)
  }, [enabled, intervalMs])

  return now
}
