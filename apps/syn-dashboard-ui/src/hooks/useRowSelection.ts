/**
 * Generic row-selection state for tables / card lists.
 *
 * Supports plain click (toggle one), Shift+click (range from anchor),
 * Cmd/Ctrl+click (toggle without clearing), select-all, and clear.
 *
 * When the underlying `items` array changes (e.g. filters narrow the view),
 * selections whose IDs no longer appear are dropped — there's no value in
 * "ghost" selections the user can't see.
 *
 * See: docs/adrs/ADR-064-observability-monitor-ui.md
 */

import { useCallback, useMemo, useState } from 'react'

export interface SelectionClickModifiers {
  shift?: boolean
  meta?: boolean
}

export interface UseRowSelectionResult<T> {
  selectedIds: Set<string>
  selectedItems: T[]
  selectedCount: number
  isSelected: (id: string) => boolean
  handleClick: (id: string, modifiers?: SelectionClickModifiers) => void
  toggle: (id: string) => void
  selectAll: () => void
  clear: () => void
}

function rangeBetween(items: { id: string }[], a: string, b: string): string[] {
  const ai = items.findIndex((i) => i.id === a)
  const bi = items.findIndex((i) => i.id === b)
  if (ai === -1 || bi === -1) return [b]
  const [lo, hi] = ai < bi ? [ai, bi] : [bi, ai]
  return items.slice(lo, hi + 1).map((i) => i.id)
}

function withToggled(prev: Set<string>, id: string): Set<string> {
  const next = new Set(prev)
  if (next.has(id)) next.delete(id)
  else next.add(id)
  return next
}

function withAdded(prev: Set<string>, ids: string[]): Set<string> {
  const next = new Set(prev)
  for (const i of ids) next.add(i)
  return next
}

function pruneToPresent(prev: Set<string>, presentIds: Set<string>): Set<string> | null {
  let changed = false
  const next = new Set<string>()
  for (const id of prev) {
    if (presentIds.has(id)) next.add(id)
    else changed = true
  }
  return changed ? next : null
}

export function useRowSelection<T extends { id: string }>(
  items: T[],
): UseRowSelectionResult<T> {
  const [selectedIds, setSelectedIds] = useState<Set<string>>(() => new Set())
  const [anchor, setAnchor] = useState<string | null>(null)
  const [prevItems, setPrevItems] = useState(items)

  if (items !== prevItems) {
    setPrevItems(items)
    const presentIds = new Set(items.map((i) => i.id))
    const pruned = pruneToPresent(selectedIds, presentIds)
    if (pruned) setSelectedIds(pruned)
    if (anchor && !presentIds.has(anchor)) {
      setAnchor(null)
    }
  }

  const isSelected = useCallback((id: string) => selectedIds.has(id), [selectedIds])

  const toggle = useCallback((id: string) => {
    setSelectedIds((prev) => withToggled(prev, id))
    setAnchor(id)
  }, [])

  const handleClick = useCallback(
    (id: string, modifiers: SelectionClickModifiers = {}) => {
      if (modifiers.shift) {
        const ids = rangeBetween(items, anchor ?? id, id)
        setSelectedIds((prev) => withAdded(prev, ids))
        return
      }
      if (modifiers.meta) {
        setSelectedIds((prev) => withToggled(prev, id))
        setAnchor(id)
        return
      }
      setSelectedIds(new Set([id]))
      setAnchor(id)
    },
    [items, anchor],
  )

  const selectAll = useCallback(() => {
    setSelectedIds(new Set(items.map((i) => i.id)))
  }, [items])

  const clear = useCallback(() => {
    setSelectedIds(new Set())
    setAnchor(null)
  }, [])

  const selectedItems = useMemo(
    () => items.filter((i) => selectedIds.has(i.id)),
    [items, selectedIds],
  )

  return {
    selectedIds,
    selectedItems,
    selectedCount: selectedIds.size,
    isSelected,
    handleClick,
    toggle,
    selectAll,
    clear,
  }
}
