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

import { useEffect, useState } from 'react'

export function useMediaQuery(query: string): boolean {
  const [matches, setMatches] = useState<boolean>(() => {
    if (typeof window === 'undefined') return false
    return window.matchMedia(query).matches
  })

  useEffect(() => {
    if (typeof window === 'undefined') return
    const mq = window.matchMedia(query)
    const handler = (e: MediaQueryListEvent) => setMatches(e.matches)
    setMatches(mq.matches)
    mq.addEventListener('change', handler)
    return () => mq.removeEventListener('change', handler)
  }, [query])

  return matches
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
