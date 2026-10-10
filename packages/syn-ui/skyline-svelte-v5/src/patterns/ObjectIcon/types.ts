import type { ObjectKind } from '@syn137/skyline-core/patterns'
import type { SVGAttributes } from 'svelte/elements'

export interface ObjectIconProps extends Omit<SVGAttributes<SVGSVGElement>, 'children'> {
  kind: ObjectKind
  /** Rendered size in px (default 64; Page Header uses 48 on phones and 84 from 48rem). */
  size?: number
  /** Accessible name. Without one the icon is decorative (aria-hidden). */
  label?: string
}
