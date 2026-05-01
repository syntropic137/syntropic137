/**
 * Reactive `window.matchMedia` wrapper.
 *
 * Returns true while the given query matches; updates on breakpoint
 * crossings. Default for SSR / no-window: false.
 *
 * Common breakpoints (Tailwind defaults):
 *   sm  >= 640px
 *   md  >= 768px
 *   lg  >= 1024px
 *
 * See: docs/adrs/ADR-064-observability-monitor-ui.md
 */

import { useCallback, useSyncExternalStore } from 'react'

export function useMediaQuery(query: string): boolean {
  const subscribe = useCallback(
    (onChange: () => void) => {
      if (typeof window === 'undefined') return () => {}
      const mq = window.matchMedia(query)
      mq.addEventListener('change', onChange)
      return () => mq.removeEventListener('change', onChange)
    },
    [query],
  )

  const getSnapshot = useCallback(() => {
    if (typeof window === 'undefined') return false
    return window.matchMedia(query).matches
  }, [query])

  const getServerSnapshot = (): boolean => false

  return useSyncExternalStore(subscribe, getSnapshot, getServerSnapshot)
}

export const BREAKPOINTS = {
  sm: '(min-width: 640px)',
  md: '(min-width: 768px)',
  lg: '(min-width: 1024px)',
  xl: '(min-width: 1280px)',
} as const

export function useIsMobile(): boolean {
  return !useMediaQuery(BREAKPOINTS.md)
}
