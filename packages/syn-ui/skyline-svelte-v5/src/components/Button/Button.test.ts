// @vitest-environment jsdom
import '../_test/setup'
import { render, screen } from '@testing-library/svelte'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { text } from '../_test/setup'
import Button from './Button.svelte'

describe('Button', () => {
  it('renders a button with variant, tone and size as data attributes', () => {
    render(Button, { children: text('View transcript') })
    const b = screen.getByRole('button', { name: 'View transcript' })
    expect(b).toHaveProperty('type', 'button')
    expect(b.dataset).toMatchObject({ variant: 'outline', tone: 'neutral', size: 'md' })
  })

  it('defaults the solid tone to accent (primary)', () => {
    render(Button, { variant: 'solid', children: text('Run') })
    expect(screen.getByRole('button').dataset.tone).toBe('accent')
  })

  it.each([
    ['primary', 'solid', 'accent'],
    ['secondary', 'outline', 'neutral'],
    ['ghost', 'ghost', 'neutral'],
    ['danger', 'outline', 'danger'],
  ] as const)('maps the upstream %s variant onto Skyline (%s, %s)', (variant, drawn, tone) => {
    render(Button, { variant, children: text('Go') })
    expect(screen.getByRole('button').dataset).toMatchObject({ variant: drawn, tone })
  })

  it('calls onclick and passes native attributes through', async () => {
    const onclick = vi.fn()
    render(Button, { onclick, title: 'hello', 'data-testid': 'b', children: text('Go') })
    await userEvent.click(screen.getByTestId('b'))
    expect(onclick).toHaveBeenCalledOnce()
    expect(screen.getByTestId('b').title).toBe('hello')
  })

  it('keeps component-owned attributes from being overridden', () => {
    render(Button, { class: 'x', 'data-variant': 'nope', variant: 'ghost', children: text('A') } as never)
    const b = screen.getByRole('button')
    expect(b.className).toContain('sky-button')
    expect(b.dataset.variant).toBe('ghost')
  })

  it('blocks clicks while loading but stays focusable', async () => {
    const onclick = vi.fn()
    render(Button, { loading: true, onclick, children: text('Save') })
    const b = screen.getByRole('button')
    expect(b.getAttribute('aria-busy')).toBe('true')
    expect(b.hasAttribute('disabled')).toBe(false)
    await userEvent.click(b)
    expect(onclick).not.toHaveBeenCalled()
  })

  it('honours disabled', async () => {
    const onclick = vi.fn()
    render(Button, { disabled: true, onclick, children: text('No') })
    await userEvent.click(screen.getByRole('button'))
    expect(onclick).not.toHaveBeenCalled()
  })

  it('renders a link when href is set', () => {
    render(Button, { href: '/workflows', children: text('Workflows') })
    expect(screen.getByRole('link', { name: 'Workflows' }).getAttribute('href')).toBe('/workflows')
  })

  it('marks icon-only buttons and uses aria-label', () => {
    render(Button, { icon: text('i'), 'aria-label': 'Copy' })
    const b = screen.getByRole('button', { name: 'Copy' })
    expect(b.dataset.iconOnly).toBe('true')
  })
})
