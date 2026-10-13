/**
 * Rows per page, held in the URL (`?rows=100`) so a chosen size survives a
 * reload and a shared link, the same as the filters beside it.
 *
 * Only a size in `choices` is honoured: anything else in the URL falls back to
 * the surface's default rather than asking the API for a page it would refuse.
 */

import { useCallback } from 'react'
import { useSearchParams } from 'react-router-dom'

export const PAGE_SIZE_PARAM = 'rows'

export function usePageSizeUrlState(
  defaultSize: number,
  choices: readonly number[],
): [number, (next: number) => void] {
  const [searchParams, setSearchParams] = useSearchParams()
  const requested = Number(searchParams.get(PAGE_SIZE_PARAM))
  const pageSize = choices.includes(requested) ? requested : defaultSize
  const setPageSize = useCallback(
    (next: number) => {
      setSearchParams(
        (prev) => {
          const out = new URLSearchParams(prev)
          if (next === defaultSize || !choices.includes(next)) out.delete(PAGE_SIZE_PARAM)
          else out.set(PAGE_SIZE_PARAM, String(next))
          return out
        },
        { replace: true },
      )
    },
    [setSearchParams, defaultSize, choices],
  )
  return [pageSize, setPageSize]
}
