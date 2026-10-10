/** Linear map from a domain to a range; clamps when `clamp` is true. */
export function scaleLinear(domain: readonly [number, number], range: readonly [number, number], clamp = false) {
  const [d0, d1] = domain
  const [r0, r1] = range
  const span = d1 - d0
  return (v: number): number => {
    const t = span === 0 ? 0 : (v - d0) / span
    const c = clamp ? Math.min(1, Math.max(0, t)) : t
    return r0 + c * (r1 - r0)
  }
}

/**
 * Square-root height for counts (the Skyline uses this so one busy day does
 * not flatten the rest): 0 -> 0, max -> maxHeight, never below `min` when > 0.
 */
export function sqrtHeight(value: number, max: number, maxHeight: number, min = 0): number {
  if (value <= 0 || max <= 0) return 0
  return Math.max(min, Math.round(maxHeight * Math.sqrt(Math.min(value, max) / max)))
}
