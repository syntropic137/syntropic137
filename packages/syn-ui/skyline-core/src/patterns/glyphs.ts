/**
 * Line glyphs drawn by the patterns, as SVG path data in a 16 x 16 box,
 * transcribed from the canvas. Plain strings, so any renderer can use them;
 * Lucide stays the source for general UI icons.
 */
import type { StatusGlyph } from './status'

export const STATUS_GLYPH_PATHS: Record<StatusGlyph, string> = {
  check: 'M3.5 8.5l3 3 6-7',
  cross: 'M4.5 4.5l7 7M11.5 4.5l-7 7',
  dash: 'M3.5 8h9',
  // A three-quarter arc; the badge spins it unless reduced motion.
  spinner: 'M8 2.75a5.25 5.25 0 1 1-5.25 5.25',
  clock: 'M8 2.75a5.25 5.25 0 1 0 0 10.5a5.25 5.25 0 1 0 0-10.5M8 5v3.25l2 1.25',
  pause: 'M6 4v8M10 4v8',
  skip: 'M4 4l5 4-5 4M11.5 4v8',
  dot: 'M8 7.25v1.5',
}

export const GLYPH = {
  terminal: 'M3 4.5L6.5 8 3 11.5M8.5 11.5H13',
  edit: 'M10.5 2.75l2.75 2.75L6 12.75l-3.25.5.5-3.25z',
  file: 'M4 1.75h5l3 3v9.5H4zM9 1.75v3h3',
  search: 'M7 2.75a4.25 4.25 0 1 0 0 8.5a4.25 4.25 0 1 0 0-8.5M10.25 10.25L13.5 13.5',
  globe: 'M8 2.25a5.75 5.75 0 1 0 0 11.5a5.75 5.75 0 1 0 0-11.5M2.25 8h11.5M8 2.25c1.6 1.6 2.4 3.5 2.4 5.75S9.6 12.15 8 13.75C6.4 12.15 5.6 10.25 5.6 8S6.4 3.85 8 2.25',
  agent: 'M5 6.5h6M5 9.5h4M3 2.75h10v8.5H7.5L4.5 13.5v-2.25H3z',
  tool: 'M9.75 2.5a3 3 0 0 0-3.4 4.1L2.75 10.2l3 3 3.6-3.6a3 3 0 0 0 4.1-3.4l-1.95 1.95-1.9-.35-.35-1.9z',
  copy: 'M5.5 5.5h8v8h-8zM10.5 5.5V2.5h-8v8h3',
  check: 'M3.5 8.5l3 3 6-7',
  external: 'M6.5 3.5h-3v9h9v-3M9 2.75h4.25V7M13 3L7.5 8.5',
  arrowRight: 'M2.5 8h10.5M9.5 4.5L13 8l-3.5 3.5',
  chevronLeft: 'M10 3.5L5.5 8l4.5 4.5',
  chevronRight: 'M6 3.5L10.5 8 6 12.5',
  diamond: 'M8 1.75L14.25 8 8 14.25 1.75 8z',
  warning: 'M8 2.25l6 10.75H2zM8 6.5v3M8 11.4v.1',
  rerun: 'M13.25 8a5.25 5.25 0 1 1-1.6-3.77M13.25 2.5v2.75H10.5',
} as const

export type GlyphName = keyof typeof GLYPH
