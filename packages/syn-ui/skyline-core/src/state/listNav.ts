/**
 * Roving focus for composite widgets (tabs, toggle groups, menus, listboxes,
 * accordion headers). Pure index arithmetic: the component maps a key to a
 * move, asks for the next index, then focuses that element itself.
 */
export type ListMove = 'next' | 'prev' | 'first' | 'last'
export type ListOrientation = 'horizontal' | 'vertical' | 'both'

/** Keyboard key -> move for a widget's orientation, or null when the key is not a navigation key. */
export function listMoveForKey(key: string, orientation: ListOrientation = 'both', dir: 'ltr' | 'rtl' = 'ltr'): ListMove | null {
  const h = orientation !== 'vertical'
  const v = orientation !== 'horizontal'
  switch (key) {
    case 'ArrowRight':
      return h ? (dir === 'rtl' ? 'prev' : 'next') : null
    case 'ArrowLeft':
      return h ? (dir === 'rtl' ? 'next' : 'prev') : null
    case 'ArrowDown':
      return v ? 'next' : null
    case 'ArrowUp':
      return v ? 'prev' : null
    case 'Home':
      return 'first'
    case 'End':
      return 'last'
    default:
      return null
  }
}

/**
 * The index focus moves to, skipping disabled items. Returns `current` when
 * nothing else is focusable, and -1 when no item is enabled at all.
 * `loop` wraps from the last item to the first and back.
 */
export function moveIndex(current: number, move: ListMove, disabled: readonly boolean[], loop = true): number {
  const n = disabled.length
  if (n === 0 || disabled.every(Boolean)) return -1
  const enabled = (i: number) => !disabled[i]
  if (move === 'first') {
    for (let i = 0; i < n; i++) if (enabled(i)) return i
  }
  if (move === 'last') {
    for (let i = n - 1; i >= 0; i--) if (enabled(i)) return i
  }
  const step = move === 'next' ? 1 : -1
  const inRange = current >= 0 && current < n
  let i = inRange ? current : step === 1 ? -1 : n
  for (let tries = 0; tries < n; tries++) {
    i += step
    if (i >= n || i < 0) {
      if (!loop) return inRange ? current : -1
      i = (i + n) % n
    }
    if (enabled(i)) return i
  }
  return current
}

/**
 * Type-to-select: the first enabled item after `from` whose label starts
 * with `query` (case-insensitive), wrapping around. -1 when none matches.
 * A query of one repeated letter cycles through items with that initial.
 */
export function typeaheadIndex(labels: readonly string[], disabled: readonly boolean[], from: number, query: string): number {
  const q = query.toLocaleLowerCase()
  if (!q) return -1
  const n = labels.length
  const repeated = q.length > 1 && [...q].every((c) => c === q[0])
  const needle = repeated ? q[0]! : q
  // A fresh multi-letter query may match the current item; a single letter moves on.
  const startOffset = needle.length > 1 ? 0 : 1
  for (let k = 0; k < n; k++) {
    const i = (((from + startOffset + k) % n) + n) % n
    if (disabled[i]) continue
    if ((labels[i] ?? '').toLocaleLowerCase().startsWith(needle)) return i
  }
  return -1
}
