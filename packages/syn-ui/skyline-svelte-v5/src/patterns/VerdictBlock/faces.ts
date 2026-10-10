import { extrudeColors, type FaceColors } from '@syn137/skyline-core/geometry'
import type { Verdict } from '@syn137/skyline-core/patterns'

/** Face colours per verdict. Unscored is a flat grey slab with its own three greys. */
export const VERDICT_FACES: Record<Verdict, FaceColors> = {
  pass: extrudeColors('var(--ds-color-accent)'),
  fail: extrudeColors('var(--ds-color-danger)'),
  error: extrudeColors('var(--ds-color-warning)'),
  unscored: { front: 'var(--sky-color-unscored)', top: 'var(--ds-color-text-subtle)', side: 'var(--sky-color-empty)' },
}
