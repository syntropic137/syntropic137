import { describe, expect, it } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import { StaleResults } from '../StaleResults'

function list(stale: boolean, failed = false) {
  return render(
    <>
      <button type="button">Filter</button>
      <StaleResults stale={stale} failed={failed} onRetry={() => {}}>
        <a href="/sessions/s-1">Session s-1</a>
        <button type="button">Row action</button>
      </StaleResults>
      <button type="button">Next page</button>
    </>,
  )
}

/**
 * Tab the way a browser does. jsdom does not implement `inert`, and
 * user-event's Tab skips only negative tabindex and disabled controls, so the
 * browser's rule - nothing inside an inert subtree takes focus - is applied
 * here before tabbing. Without `inert` on the rows this changes nothing.
 */
async function tabFrom(name: string) {
  for (const el of document.querySelectorAll('[inert] *')) el.setAttribute('tabindex', '-1')
  const user = userEvent.setup()
  await user.click(screen.getByRole('button', { name }))
  await user.tab()
}

describe('StaleResults', () => {
  it('keeps stale rows out of the tab order, so the keyboard cannot act on them', async () => {
    list(true)

    await tabFrom('Filter')

    // The defect: only `pointer-events-none` made the rows inert, and Tab
    // walked straight into a row link answering the previous filter.
    expect(screen.getByRole('button', { name: 'Next page' })).toHaveFocus()
  })

  it('leaves Retry reachable while the rows it would refresh are inert', async () => {
    list(true, true)

    await tabFrom('Filter')

    expect(screen.getByRole('button', { name: 'Retry' })).toHaveFocus()
  })

  it('leaves current rows reachable by keyboard', async () => {
    list(false)

    await tabFrom('Filter')

    expect(screen.getByRole('link', { name: 'Session s-1' })).toHaveFocus()
  })
})
