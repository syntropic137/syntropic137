/**
 * Tests for FilterChip primitive.
 */

import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { FilterChip } from '../FilterChip'

describe('FilterChip', () => {
  it('renders the label', () => {
    render(<FilterChip label="running" isActive={false} onClick={() => {}} />)
    expect(screen.getByRole('button', { name: /running/i })).toBeTruthy()
  })

  it('renders the count when provided', () => {
    render(<FilterChip label="failed" count={7} isActive={false} onClick={() => {}} />)
    expect(screen.getByText('7')).toBeTruthy()
  })

  it('reflects active state via aria-pressed', () => {
    const { rerender } = render(
      <FilterChip label="x" isActive={false} onClick={() => {}} />,
    )
    expect(screen.getByRole('button').getAttribute('aria-pressed')).toBe('false')
    rerender(<FilterChip label="x" isActive={true} onClick={() => {}} />)
    expect(screen.getByRole('button').getAttribute('aria-pressed')).toBe('true')
  })

  it('fires onClick when clicked', () => {
    const onClick = vi.fn()
    render(<FilterChip label="x" isActive={false} onClick={onClick} />)
    fireEvent.click(screen.getByRole('button'))
    expect(onClick).toHaveBeenCalledOnce()
  })

  it('does not fire onClick when disabled', () => {
    const onClick = vi.fn()
    render(<FilterChip label="x" isActive={false} disabled onClick={onClick} />)
    fireEvent.click(screen.getByRole('button'))
    expect(onClick).not.toHaveBeenCalled()
  })
})
