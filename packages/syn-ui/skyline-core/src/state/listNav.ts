/**
 * Roving focus for composite widgets (tabs, toggle groups, menus, listboxes,
 * accordion headers). Pure index arithmetic: the component maps a key to a
 * move, asks for the next index, then focuses that element itself.
 */
export type ListMove = 'next' | 'prev' | 'first' | 'last'
export type ListOrientation = 'horizontal' | 'vertical' | 'both'

/** Navigation keys: the axis they belong to and the move in each reading direction. */
const KEY_MOVES: Record<string, { axis: 'h' | 'v' | 'any'; ltr: ListMove; rtl: ListMove }> = {
  ArrowRight: { axis: 'h', ltr: 'next', rtl: 'prev' },
  ArrowLeft: { axis: 'h', ltr: 'prev', rtl: 'next' },
  ArrowDown: { axis: 'v', ltr: 'next', rtl: 'next' },
  ArrowUp: { axis: 'v', ltr: 'prev', rtl: 'prev' },
  Home: { axis: 'any', ltr: 'first', rtl: 'first' },
  End: { axis: 'any', ltr: 'last', rtl: 'last' },
}

/** Orientation that excludes each axis. */
const EXCLUDED_BY: Record<'h' | 'v', ListOrientation> = { h: 'vertical', v: 'horizontal' }

/** Keyboard key -> move for a widget's orientation, or null when the key is not a navigation key. */
export function listMoveForKey(key: string, orientation: ListOrientation = 'both', dir: 'ltr' | 'rtl' = 'ltr'): ListMove | null {
  const entry = Object.hasOwn(KEY_MOVES, key) ? KEY_MOVES[key] : undefined
  if (!entry) return null
  if (entry.axis !== 'any' && orientation === EXCLUDED_BY[entry.axis]) return null
  return entry[dir]
}

/**
 * The index focus moves to, skipping disabled items. Returns `current` when
 * nothing else is focusable, and -1 when no item is enabled at all.
 * `loop` wraps from the last item to the first and back.
 */
export function moveIndex(current: number, move: ListMove, disabled: readonly boolean[], loop = true): number {
  const n = disabled.length
  if (n === 0 || disabled.every(Boolean)) return -1
  if (move === 'first') return disabled.findIndex((d) => !d)
  if (move === 'last') return lastEnabledIndex(disabled)
  return stepIndex(current, move === 'next' ? 1 : -1, disabled, loop)
}

function lastEnabledIndex(disabled: readonly boolean[]): number {
  for (let i = disabled.length - 1; i >= 0; i--) if (!disabled[i]) return i
  return -1
}

/** Walk one step at a time from `current`, wrapping when `loop`, to the next enabled item. */
function stepIndex(current: number, step: 1 | -1, disabled: readonly boolean[], loop: boolean): number {
  const n = disabled.length
  const inRange = current >= 0 && current < n
  const stuck = inRange ? current : -1
  let i = startIndex(inRange, current, step, n)
  for (let tries = 0; tries < n; tries++) {
    i += step
    const outside = i >= n || i < 0
    if (outside && !loop) return stuck
    if (outside) i = (i + n) % n
    if (!disabled[i]) return i
  }
  return current
}

function startIndex(inRange: boolean, current: number, step: 1 | -1, n: number): number {
  if (inRange) return current
  return step === 1 ? -1 : n
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
