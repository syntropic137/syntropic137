import type { Verdict } from '@syn137/skyline-core/patterns'
import type { SVGAttributes } from 'svelte/elements'

export interface VerdictBlockProps extends Omit<SVGAttributes<SVGSVGElement>, 'children'> {
  verdict: Verdict
  /** Width in px; height follows the 56 x 48 box (default 56, 44 in lists). */
  size?: number
  /** Accessible name; decorative without one. */
  label?: string
}
