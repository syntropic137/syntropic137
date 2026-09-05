/**
 * What a list surface asks for, and which collection it is asking about.
 *
 * `useListQuery` does not fetch and returns no `total`, so the count
 * assertions that pin `useExecutionList` and `useArtifactList` are not
 * expressible against it. What it decides instead is the thing those counts
 * are a count OF: a page number means nothing except relative to a collection,
 * and #1159 was two surfaces disagreeing about which collection they were on.
 *
 * So these assert the decisions it makes on everyone's behalf - that a
 * narrowed collection is asked about from page 1, that a search term settles
 * before it travels, and that a query nobody changed is the same query.
 */

import { describe, expect, it, vi, afterEach } from 'vitest'
import { act, renderHook } from '@testing-library/react'
import { createElement, type ReactNode } from 'react'
import { MemoryRouter } from 'react-router-dom'

import type { ListQuery } from '../../api/listQuery'
import { LIST_PAGE_SIZE, useListQuery } from '../useListQuery'

const SEARCH_DEBOUNCE_MS = 300

function wrapperAt(url: string) {
  return function Wrapper({ children }: { children: ReactNode }) {
    return createElement(MemoryRouter, { initialEntries: [url] }, children)
  }
}

/** Render, recording the query produced by EVERY render rather than the last. */
function renderRecording(url: string, scopeKey = '') {
  const seen: ListQuery[] = []
  const rendered = renderHook(
    () => {
      const state = useListQuery(scopeKey)
      seen.push(state.query)
      return state
    },
    { wrapper: wrapperAt(url) },
  )
  return { ...rendered, seen }
}

describe('useListQuery', () => {
  afterEach(() => {
    vi.useRealTimers()
  })

  it('asks for the first page of the shared page size', () => {
    const { result } = renderHook(() => useListQuery(''), { wrapper: wrapperAt('/') })

    expect(result.current.query.page).toBe(1)
    expect(result.current.query.page_size).toBe(LIST_PAGE_SIZE)
    expect(result.current.query.statuses).toBeUndefined()
    expect(result.current.query.q).toBeUndefined()
  })

  it('carries the default window as a bound the API will accept', () => {
    const { result } = renderHook(() => useListQuery(''), { wrapper: wrapperAt('/') })

    // A timezone-less bound is a 422 from the API (#1183).
    expect(result.current.query.started_after).toMatch(/(Z|[+-]\d{2}:\d{2})$/)
  })

  it('drops the bound entirely for the All window rather than sending a far one', () => {
    const { result } = renderHook(() => useListQuery(''), {
      wrapper: wrapperAt('/?timeWindow=all'),
    })

    expect(result.current.query.started_after).toBeUndefined()
    expect(result.current.timeWindow).toBe('all')
  })

  it('sorts the status filter, so two surfaces asking the same thing ask identically', () => {
    const { result } = renderHook(() => useListQuery(''), {
      wrapper: wrapperAt('/?status=running,failed'),
    })

    expect(result.current.query.statuses).toEqual(['failed', 'running'])
  })

  it('keeps the query referentially stable when nothing that defines it changed', () => {
    const { result, rerender } = renderHook(() => useListQuery(''), {
      wrapper: wrapperAt('/'),
    })

    const first = result.current.query
    rerender()

    // It is documented as safe to use as a fetch dependency; a fresh object
    // per render would refetch forever.
    expect(result.current.query).toBe(first)
  })

  it('holds the page while paging within one collection', () => {
    const { result } = renderHook(() => useListQuery(''), { wrapper: wrapperAt('/') })

    act(() => result.current.setPage(3))

    expect(result.current.query.page).toBe(3)
  })

  it('clamps the page at 1 rather than asking for a page before the first', () => {
    const { result } = renderHook(() => useListQuery(''), { wrapper: wrapperAt('/') })

    act(() => result.current.setPage(0))
    expect(result.current.query.page).toBe(1)

    act(() => result.current.setPage(-5))
    expect(result.current.query.page).toBe(1)
  })

  it('narrowing the collection asks for its first page, never the held page of it', () => {
    const { result, seen } = renderRecording('/')

    act(() => result.current.setPage(3))
    expect(result.current.query.page).toBe(3)

    act(() => result.current.toggleStatus('failed'))

    expect(result.current.query.statuses).toEqual(['failed'])
    expect(result.current.query.page).toBe(1)
    // Derived from the collection's identity rather than corrected by an
    // effect: an effect would render page 3 of the NEW collection first and
    // fetch it, which on a filter that narrows past page 3 is an empty list.
    const askedForPage3OfTheNewCollection = seen.some(
      (query) => query.page === 3 && query.statuses?.includes('failed'),
    )
    expect(askedForPage3OfTheNewCollection).toBe(false)
  })

  it('treats a change of the caller-owned scope as a change of collection', () => {
    const { result, rerender } = renderHook(({ scope }) => useListQuery(scope), {
      wrapper: wrapperAt('/'),
      initialProps: { scope: 'wf-1' },
    })

    act(() => result.current.setPage(2))
    expect(result.current.query.page).toBe(2)

    // Artifacts' workflow/phase/type narrowing is invisible to this hook, so
    // it arrives as a scope key and must reset the page just as a chip does.
    rerender({ scope: 'wf-2' })

    expect(result.current.query.page).toBe(1)
  })

  it('widening the window is also a change of collection', () => {
    const { result } = renderHook(() => useListQuery(''), { wrapper: wrapperAt('/') })

    act(() => result.current.setPage(2))
    act(() => result.current.setTimeWindow('all'))

    expect(result.current.query.page).toBe(1)
  })

  it('settles the search term before it travels', () => {
    vi.useFakeTimers()
    const { result } = renderHook(() => useListQuery(''), { wrapper: wrapperAt('/') })

    act(() => result.current.setSearchQuery('alp'))

    // Visible in the box immediately, but not yet on the query.
    expect(result.current.searchQuery).toBe('alp')
    expect(result.current.query.q).toBeUndefined()

    act(() => vi.advanceTimersByTime(SEARCH_DEBOUNCE_MS - 1))
    expect(result.current.query.q).toBeUndefined()

    act(() => vi.advanceTimersByTime(1))
    expect(result.current.query.q).toBe('alp')
  })

  it('trims the settled term, and sends no term at all for an empty one', () => {
    vi.useFakeTimers()
    const { result } = renderHook(() => useListQuery(''), { wrapper: wrapperAt('/') })

    act(() => result.current.setSearchQuery('  alpha  '))
    act(() => vi.advanceTimersByTime(SEARCH_DEBOUNCE_MS))
    expect(result.current.query.q).toBe('alpha')

    act(() => result.current.setSearchQuery('   '))
    act(() => vi.advanceTimersByTime(SEARCH_DEBOUNCE_MS))
    // Not the empty string: the API would read that as a filter matching
    // everything with a `q` on the wire, which is not the same request.
    expect(result.current.query.q).toBeUndefined()
  })

  it('reports whether the shared filters are at their defaults', () => {
    const { result } = renderHook(() => useListQuery(''), { wrapper: wrapperAt('/') })
    expect(result.current.isDefaultFilters).toBe(true)

    act(() => result.current.toggleStatus('failed'))
    expect(result.current.isDefaultFilters).toBe(false)

    act(() => result.current.clearStatuses())
    expect(result.current.isDefaultFilters).toBe(true)

    act(() => result.current.setTimeWindow('7d'))
    expect(result.current.isDefaultFilters).toBe(false)
  })
})
