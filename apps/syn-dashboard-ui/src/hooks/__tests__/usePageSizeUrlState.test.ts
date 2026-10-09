/**
 * The Executions/Sessions page-size picker (feedback 60d9f990). The choice
 * lives in the URL, and only a size the surface offers is ever sent.
 */

import { describe, expect, it } from 'vitest'
import { act, renderHook } from '@testing-library/react'
import { createElement, type ReactNode } from 'react'
import { MemoryRouter } from 'react-router-dom'

import { RUN_LIST_PAGE_SIZES, useListQuery } from '../useListQuery'
import { usePageSizeUrlState } from '../usePageSizeUrlState'

function wrapperAt(url: string) {
  return function Wrapper({ children }: { children: ReactNode }) {
    return createElement(MemoryRouter, { initialEntries: [url] }, children)
  }
}

/** The picker feeding the query, the way `useServerList` composes them. */
function usePickedQuery(defaultSize: number) {
  const [pageSize, setPageSize] = usePageSizeUrlState(defaultSize, RUN_LIST_PAGE_SIZES)
  const { query, setPage } = useListQuery('', pageSize)
  return { query, setPage, setPageSize }
}

describe('usePageSizeUrlState', () => {
  it('opens at the surface default and sends the picked size', () => {
    const { result } = renderHook(() => usePickedQuery(50), { wrapper: wrapperAt('/') })
    expect(result.current.query.page_size).toBe(50)

    act(() => result.current.setPageSize(100))

    expect(result.current.query.page_size).toBe(100)
  })

  it('honours a size in the URL only when the surface offers it', () => {
    const offered = renderHook(() => usePickedQuery(50), { wrapper: wrapperAt('/?rows=100') })
    expect(offered.result.current.query.page_size).toBe(100)

    const refused = renderHook(() => usePickedQuery(50), { wrapper: wrapperAt('/?rows=5000') })
    expect(refused.result.current.query.page_size).toBe(50)
  })

  it('returns to page 1 when the size changes', () => {
    const { result } = renderHook(() => usePickedQuery(50), { wrapper: wrapperAt('/') })
    act(() => result.current.setPage(3))
    expect(result.current.query.page).toBe(3)

    act(() => result.current.setPageSize(100))

    expect(result.current.query.page).toBe(1)
  })
})
