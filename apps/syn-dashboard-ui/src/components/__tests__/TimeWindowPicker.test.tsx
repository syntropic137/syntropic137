/**
 * Tests for TimeWindowPicker.
 *
 * The component renders both the mobile <select> and the desktop segmented
 * control simultaneously (CSS hides whichever does not fit). Tests target
 * each via role / aria-label.
 */

import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { TimeWindowPicker } from '../TimeWindowPicker'

describe('TimeWindowPicker', () => {
  it('marks the selected option as active in the segmented control', () => {
    render(<TimeWindowPicker value="24h" onChange={() => {}} />)
    const radios = screen.getAllByRole('radio')
    const checked = radios.filter((r) => r.getAttribute('aria-checked') === 'true')
    expect(checked).toHaveLength(1)
    expect(checked[0].textContent).toBe('24h')
  })

  it('fires onChange when a different segment is clicked', () => {
    const onChange = vi.fn()
    render(<TimeWindowPicker value="24h" onChange={onChange} />)
    fireEvent.click(screen.getByRole('radio', { name: '7d' }))
    expect(onChange).toHaveBeenCalledWith('7d')
  })

  it('fires onChange when the mobile select changes', () => {
    const onChange = vi.fn()
    render(<TimeWindowPicker value="24h" onChange={onChange} />)
    const select = screen.getByLabelText('Time window', { selector: 'select' })
    fireEvent.change(select, { target: { value: 'all' } })
    expect(onChange).toHaveBeenCalledWith('all')
  })
})
