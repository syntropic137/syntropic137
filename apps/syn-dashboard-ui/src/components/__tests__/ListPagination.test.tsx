/**
 * The count line, including the rows the window could not judge (#1215).
 *
 * This is the last hop: the number is computed in the domain, carried through
 * the API response model, the generated types and the hook, and if it stops
 * here nobody ever sees it and none of the rest mattered. 274 of 1037
 * artifacts carry no date, so "of 755" was the only thing a reader was told.
 */

import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { ListPagination } from '../ListPagination'

const noop = () => {}

describe('ListPagination', () => {
  it('says how many rows the window could not place in time', () => {
    render(
      <ListPagination
        page={1}
        pageSize={50}
        total={755}
        excludedUndated={274}
        onPageChange={noop}
        itemLabel="artifact"
      />,
    )

    expect(screen.getByText(/Showing 1-50 of 755 artifacts/)).toBeTruthy()
    expect(screen.getByText(/274 undated/)).toBeTruthy()
  })

  it('says nothing about undated rows when there are none', () => {
    render(
      <ListPagination
        page={1}
        pageSize={50}
        total={755}
        excludedUndated={0}
        onPageChange={noop}
        itemLabel="artifact"
      />,
    )

    expect(screen.queryByText(/undated/)).toBeNull()
  })

  it('still speaks when the window matched nothing but excluded rows', () => {
    // The case the line matters most for: an empty list plus a silent
    // exclusion reads as "there is nothing", which is the opposite of true.
    render(
      <ListPagination
        page={1}
        pageSize={50}
        total={0}
        excludedUndated={274}
        onPageChange={noop}
        itemLabel="artifact"
      />,
    )

    expect(screen.getByText(/274 undated/)).toBeTruthy()
    expect(screen.queryByText(/Showing/)).toBeNull()
  })

  it('renders nothing at all when there is genuinely nothing to describe', () => {
    const { container } = render(
      <ListPagination page={1} pageSize={50} total={0} onPageChange={noop} itemLabel="artifact" />,
    )

    expect(container.textContent).toBe('')
  })
})
