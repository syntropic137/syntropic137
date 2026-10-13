// @vitest-environment jsdom
// Eval Explorer: verdict, keyboard, click
import '../../components/_test/setup'
import { fireEvent, render, screen } from '@testing-library/svelte'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import EvalExplorer from './EvalExplorer.svelte'
import { EVAL_EXPLORER_EXAMPLE } from './examples'

describe('Eval Explorer', () => {
  it('picks the best quality per dollar and writes its verdict', () => {
    render(EvalExplorer, { ...EVAL_EXPLORER_EXAMPLE })
    const picked = screen.getByRole('radio', { checked: true })
    expect(picked.textContent).toContain('claude-sonnet-5-5')
    expect(picked.getAttribute('tabindex')).toBe('0')
    expect(screen.getByText('Up 29 points since its first runs, at the same cost.')).toBeTruthy()
    expect(screen.getByText('/100 · $0.52 a run · +29 pts')).toBeTruthy()
  })
  it('moves the pick with the arrow keys, Home and End, and keeps focus on it', async () => {
    const onselect = vi.fn()
    render(EvalExplorer, { ...EVAL_EXPLORER_EXAMPLE, onselect })
    screen.getByRole('radio', { checked: true }).focus()
    await userEvent.keyboard('{ArrowDown}')
    expect(onselect).toHaveBeenLastCalledWith(3)
    expect(document.activeElement?.textContent).toContain('gpt-5.6-terra')
    expect(screen.getByRole('radio', { checked: true }).textContent).toContain('gpt-5.6-terra')
    await userEvent.keyboard('{ArrowUp}{ArrowUp}')
    expect(onselect).toHaveBeenLastCalledWith(0)
    await userEvent.keyboard('{Home}')
    expect(onselect).toHaveBeenLastCalledWith(1)
    await userEvent.keyboard('{End}')
    expect(onselect).toHaveBeenLastCalledWith(0)
    expect(screen.getByText('Up 15 points since its first runs, and $0.17 cheaper per run.')).toBeTruthy()
  })
  it('picks on click', async () => {
    const onselect = vi.fn()
    render(EvalExplorer, { ...EVAL_EXPLORER_EXAMPLE, onselect })
    await fireEvent.click(screen.getByRole('radio', { name: /gpt-5\.6-sol/ }))
    expect(onselect).toHaveBeenCalledWith(2)
    expect(screen.getByText('Down 10 points since its first runs, while costing $0.11 more per run.')).toBeTruthy()
  })
})
