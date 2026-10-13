/**
 * Value sets for toggle groups and accordions.
 *
 * `single` keeps at most one value. `allowEmpty: false` makes a single group
 * behave like a segmented control (Rendered / Raw): pressing the pressed item
 * keeps it pressed. An accordion's `collapsible` maps to `allowEmpty`.
 */
export type SelectionType = 'single' | 'multiple'

export function toggleValue(current: readonly string[], item: string, type: SelectionType, allowEmpty = true): string[] {
  const has = current.includes(item)
  if (type === 'single') {
    if (has) return allowEmpty ? [] : [item]
    return [item]
  }
  return has ? current.filter((v) => v !== item) : [...current, item]
}

/** Tri-state for a "select all" checkbox over `all` given the `selected` set. */
export function selectAllState(selected: readonly string[], all: readonly string[]): boolean | 'indeterminate' {
  if (all.length === 0) return false
  const set = new Set(selected)
  const n = all.filter((v) => set.has(v)).length
  if (n === 0) return false
  return n === all.length ? true : 'indeterminate'
}
