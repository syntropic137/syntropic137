import { describe, expect, it } from 'vitest'
import { act, renderHook } from '@testing-library/react'
import { useRowSelection } from '../useRowSelection'

const items = [
  { id: 'a' },
  { id: 'b' },
  { id: 'c' },
  { id: 'd' },
  { id: 'e' },
]

describe('useRowSelection', () => {
  it('starts with empty selection', () => {
    const { result } = renderHook(() => useRowSelection(items))
    expect(result.current.selectedCount).toBe(0)
    expect(result.current.selectedItems).toEqual([])
  })

  it('plain click selects only that row', () => {
    const { result } = renderHook(() => useRowSelection(items))
    act(() => result.current.handleClick('b'))
    expect(result.current.selectedIds).toEqual(new Set(['b']))

    act(() => result.current.handleClick('d'))
    expect(result.current.selectedIds).toEqual(new Set(['d']))
  })

  it('cmd+click toggles without clearing others', () => {
    const { result } = renderHook(() => useRowSelection(items))
    act(() => result.current.handleClick('b', { meta: true }))
    act(() => result.current.handleClick('d', { meta: true }))
    expect(result.current.selectedIds).toEqual(new Set(['b', 'd']))

    act(() => result.current.handleClick('b', { meta: true }))
    expect(result.current.selectedIds).toEqual(new Set(['d']))
  })

  it('shift+click selects range from anchor', () => {
    const { result } = renderHook(() => useRowSelection(items))
    act(() => result.current.handleClick('b'))
    act(() => result.current.handleClick('d', { shift: true }))
    expect(result.current.selectedIds).toEqual(new Set(['b', 'c', 'd']))
  })

  it('shift+click works in reverse direction', () => {
    const { result } = renderHook(() => useRowSelection(items))
    act(() => result.current.handleClick('d'))
    act(() => result.current.handleClick('a', { shift: true }))
    expect(result.current.selectedIds).toEqual(new Set(['a', 'b', 'c', 'd']))
  })

  it('selectAll selects every item', () => {
    const { result } = renderHook(() => useRowSelection(items))
    act(() => result.current.selectAll())
    expect(result.current.selectedCount).toBe(5)
  })

  it('clear empties selection', () => {
    const { result } = renderHook(() => useRowSelection(items))
    act(() => result.current.selectAll())
    act(() => result.current.clear())
    expect(result.current.selectedCount).toBe(0)
  })

  it('drops selections whose ids disappear from items', () => {
    const { result, rerender } = renderHook(({ list }) => useRowSelection(list), {
      initialProps: { list: items },
    })
    act(() => {
      result.current.handleClick('a', { meta: true })
      result.current.handleClick('b', { meta: true })
      result.current.handleClick('c', { meta: true })
    })
    expect(result.current.selectedCount).toBe(3)

    rerender({ list: [{ id: 'a' }, { id: 'c' }] })
    expect(result.current.selectedIds).toEqual(new Set(['a', 'c']))
  })

  it('keeps selectedItems in row order', () => {
    const { result } = renderHook(() => useRowSelection(items))
    act(() => {
      result.current.handleClick('d', { meta: true })
      result.current.handleClick('a', { meta: true })
      result.current.handleClick('c', { meta: true })
    })
    expect(result.current.selectedItems.map((i) => i.id)).toEqual(['a', 'c', 'd'])
  })

  it('isSelected reflects current state', () => {
    const { result } = renderHook(() => useRowSelection(items))
    act(() => result.current.handleClick('b'))
    expect(result.current.isSelected('b')).toBe(true)
    expect(result.current.isSelected('a')).toBe(false)
  })
})
