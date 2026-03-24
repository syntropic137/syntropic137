import { useEffect } from 'react'

/**
 * Generic polling hook. Calls `callback` every `intervalMs` while `enabled` is true.
 * Cleans up automatically on unmount or when disabled.
 */
export function usePolling(
  callback: () => void,
  intervalMs: number,
  enabled: boolean,
): void {
  useEffect(() => {
    if (!enabled) return

    const id = setInterval(callback, intervalMs)
    return () => clearInterval(id)
  }, [callback, intervalMs, enabled])
}
