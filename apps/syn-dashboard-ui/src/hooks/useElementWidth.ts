/**
 * The rendered CSS-pixel width of an element, kept current with a
 * ResizeObserver. `fallback` until it is measured, and wherever there is no
 * ResizeObserver (jsdom).
 *
 * Lets an SVG use its real width as its viewBox width, so one user unit is
 * one pixel and a fontSize of 11 renders at 11px on a phone as on a desktop.
 *
 * Returns a callback ref, so an element mounted after the first render (a
 * chart that appears once data arrives) is still observed.
 */

import { useCallback, useRef, useState } from 'react'

export function useElementWidth<E extends Element>(fallback: number): [(el: E | null) => void, number] {
  const [width, setWidth] = useState(fallback)
  const observer = useRef<ResizeObserver | null>(null)

  const ref = useCallback((el: E | null) => {
    observer.current?.disconnect()
    observer.current = null
    if (!el || typeof ResizeObserver === 'undefined') return
    observer.current = new ResizeObserver(([entry]) => {
      const measured = Math.round(entry.contentRect.width)
      if (measured > 0) setWidth(measured)
    })
    observer.current.observe(el)
  }, [])

  return [ref, width]
}
