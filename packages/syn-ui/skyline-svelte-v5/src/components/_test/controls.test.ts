// @vitest-environment jsdom
// Toggle, Toggle Group, Switch, Checkbox, Select, Tabs, Pagination, Input, Tag.
import './setup'
import { render, screen } from '@testing-library/svelte'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { text } from './setup'
import Checkbox from '../Checkbox/Checkbox.svelte'
import Input from '../Input/Input.svelte'
import Pagination from '../Pagination/Pagination.svelte'
import Select from '../Select/Select.svelte'
import Switch from '../Switch/Switch.svelte'
import Tag from '../Tag/Tag.svelte'
import Toggle from '../Toggle/Toggle.svelte'
import ToggleGroup from '../ToggleGroup/ToggleGroup.svelte'
import TabsHarness from './TabsHarness.svelte'

describe('Toggle', () => {
  it('toggles aria-pressed uncontrolled and reports changes', async () => {
    const onPressedChange = vi.fn()
    render(Toggle, { children: text('Expand all'), onPressedChange })
    const b = screen.getByRole('button', { name: 'Expand all' })
    expect(b.getAttribute('aria-pressed')).toBe('false')
    await userEvent.click(b)
    expect(b.getAttribute('aria-pressed')).toBe('true')
    expect(b.dataset.state).toBe('on')
    expect(onPressedChange).toHaveBeenLastCalledWith(true)
  })
  it('starts from defaultPressed and respects disabled', async () => {
    const onPressedChange = vi.fn()
    render(Toggle, { defaultPressed: true, disabled: true, children: text('X'), onPressedChange })
    const b = screen.getByRole('button')
    expect(b.getAttribute('aria-pressed')).toBe('true')
    await userEvent.click(b)
    expect(onPressedChange).not.toHaveBeenCalled()
  })
})

describe('ToggleGroup', () => {
  const items = [
    { value: 'all', label: 'All', count: 75 },
    { value: 'completed', label: 'Completed', count: 50 },
    { value: 'failed', label: 'Failed', count: 23, disabled: true },
    { value: 'cancelled', label: 'Cancelled', count: 2 },
  ]

  it('single: radio semantics, arrows move the choice and skip disabled', async () => {
    const onValueChange = vi.fn()
    render(ToggleGroup, { type: 'single', items, defaultValue: ['all'], onValueChange, 'aria-label': 'Status' })
    expect(screen.getByRole('radiogroup', { name: 'Status' })).toBeTruthy()
    const all = screen.getByRole('radio', { name: 'All 75' })
    expect(all.getAttribute('aria-checked')).toBe('true')
    expect(all.tabIndex).toBe(0)
    all.focus()
    await userEvent.keyboard('{ArrowRight}')
    expect(onValueChange).toHaveBeenLastCalledWith(['completed'])
    await userEvent.keyboard('{ArrowRight}')
    expect(document.activeElement).toBe(screen.getByRole('radio', { name: 'Cancelled 2' }))
    expect(onValueChange).toHaveBeenLastCalledWith(['cancelled'])
  })

  it('single keeps one item pressed unless allowEmpty', async () => {
    const onValueChange = vi.fn()
    render(ToggleGroup, { type: 'single', items, defaultValue: ['all'], onValueChange })
    await userEvent.click(screen.getByRole('radio', { name: 'All 75' }))
    expect(onValueChange).not.toHaveBeenCalled()
  })

  it('multiple: aria-pressed buttons, arrows move focus only', async () => {
    const onValueChange = vi.fn()
    render(ToggleGroup, { type: 'multiple', variant: 'chips', items, onValueChange })
    expect(screen.getByRole('group')).toBeTruthy()
    const completed = screen.getByRole('button', { name: 'Completed 50' })
    await userEvent.click(completed)
    expect(completed.getAttribute('aria-pressed')).toBe('true')
    await userEvent.click(screen.getByRole('button', { name: 'Cancelled 2' }))
    expect(onValueChange).toHaveBeenLastCalledWith(['completed', 'cancelled'])
    completed.focus()
    await userEvent.keyboard('{End}')
    expect(document.activeElement).toBe(screen.getByRole('button', { name: 'Cancelled 2' }))
    expect(onValueChange).toHaveBeenCalledTimes(2)
  })
})

describe('Switch', () => {
  it('is a switch with aria-checked and a clickable label', async () => {
    const onCheckedChange = vi.fn()
    render(Switch, { children: text('Active'), onCheckedChange, name: 'active' })
    const sw = screen.getByRole('switch', { name: 'Active' })
    expect(sw.getAttribute('aria-checked')).toBe('false')
    await userEvent.click(screen.getByText('Active'))
    expect(sw.getAttribute('aria-checked')).toBe('true')
    expect(onCheckedChange).toHaveBeenLastCalledWith(true)
    expect(document.querySelector<HTMLInputElement>('input[type=hidden][name=active]')?.value).toBe('on')
    sw.focus()
    await userEvent.keyboard(' ')
    expect(sw.getAttribute('aria-checked')).toBe('false')
  })
})

describe('Checkbox', () => {
  it('checks via its label and reports booleans', async () => {
    const onCheckedChange = vi.fn()
    render(Checkbox, { children: text('Select row'), onCheckedChange })
    const box = screen.getByRole('checkbox', { name: 'Select row' }) as HTMLInputElement
    await userEvent.click(screen.getByText('Select row'))
    expect(box.checked).toBe(true)
    expect(onCheckedChange).toHaveBeenLastCalledWith(true)
  })
  it('draws indeterminate as mixed', () => {
    render(Checkbox, { checked: 'indeterminate', 'aria-label': 'Select all' })
    const box = screen.getByRole('checkbox', { name: 'Select all' }) as HTMLInputElement
    expect(box.indeterminate).toBe(true)
    expect(box.getAttribute('aria-checked')).toBe('mixed')
  })
})

describe('Select', () => {
  it('labels the native select with its prefix and reports the value', async () => {
    const onValueChange = vi.fn()
    render(Select, {
      label: 'Sort',
      options: [
        { value: 'runs', label: 'Most run' },
        { value: 'name', label: 'Name' },
      ],
      onValueChange,
    })
    const select = screen.getByRole('combobox', { name: 'Sort' }) as HTMLSelectElement
    expect(select.value).toBe('runs')
    await userEvent.selectOptions(select, 'name')
    expect(onValueChange).toHaveBeenLastCalledWith('name')
  })
})

describe('Tabs', () => {
  it('selects on arrow in automatic mode and links tab and panel', async () => {
    const onValueChange = vi.fn()
    render(TabsHarness, { onValueChange })
    const rendered = screen.getByRole('tab', { name: 'Rendered' })
    expect(rendered.getAttribute('aria-selected')).toBe('true')
    const panel = screen.getByRole('tabpanel')
    expect(panel.getAttribute('aria-labelledby')).toBe(rendered.id)
    rendered.focus()
    await userEvent.keyboard('{ArrowRight}')
    expect(onValueChange).toHaveBeenLastCalledWith('raw')
    expect(screen.getByRole('tabpanel').textContent).toContain('Panel raw')
    // JSON is disabled: wrap back to Rendered.
    await userEvent.keyboard('{ArrowRight}')
    expect(document.activeElement).toBe(rendered)
  })
  it('waits for activation in manual mode', async () => {
    const onValueChange = vi.fn()
    render(TabsHarness, { activationMode: 'manual', onValueChange })
    screen.getByRole('tab', { name: 'Rendered' }).focus()
    await userEvent.keyboard('{ArrowRight}')
    expect(onValueChange).not.toHaveBeenCalled()
    await userEvent.keyboard('{Enter}')
    expect(onValueChange).toHaveBeenLastCalledWith('raw')
  })
})

describe('Pagination', () => {
  it('shows the count and disables Previous on the first page', async () => {
    const onPageChange = vi.fn()
    render(Pagination, { page: 1, pageCount: 3, summary: 'Showing 12 of 27 workflows', onPageChange })
    expect(screen.getByRole('navigation', { name: 'Pagination' }).textContent).toContain('Showing 12 of 27 workflows')
    expect((screen.getByRole('button', { name: 'Previous' }) as HTMLButtonElement).disabled).toBe(true)
    await userEvent.click(screen.getByRole('button', { name: 'Next' }))
    expect(onPageChange).toHaveBeenLastCalledWith(2)
  })
  it('numbers pages with aria-current in pages mode', async () => {
    const onPageChange = vi.fn()
    render(Pagination, { page: 10, pageCount: 20, mode: 'pages', onPageChange })
    expect(screen.getByRole('button', { name: 'Page 10' }).getAttribute('aria-current')).toBe('page')
    await userEvent.click(screen.getByRole('button', { name: 'Page 20' }))
    expect(onPageChange).toHaveBeenLastCalledWith(20)
  })
})

describe('Input', () => {
  it('links its message and marks invalid', () => {
    render(Input, { 'aria-label': 'Max attempts', value: '0', message: 'Must be at least 1.', invalid: true })
    const input = screen.getByRole('textbox', { name: 'Max attempts' })
    expect(input.getAttribute('aria-invalid')).toBe('true')
    const msg = document.getElementById(input.getAttribute('aria-describedby')!)
    expect(msg?.textContent).toContain('Must be at least 1.')
  })
  it('updates its bound value', async () => {
    render(Input, { type: 'search', 'aria-label': 'Search', placeholder: 'Search by name or ID' })
    const input = screen.getByRole('searchbox', { name: 'Search' }) as HTMLInputElement
    await userEvent.type(input, 'resea')
    expect(input.value).toBe('resea')
  })
})

describe('Tag', () => {
  it('is static by default and a button when removable', async () => {
    const onremove = vi.fn()
    render(Tag, { variant: 'accent', onremove, children: text('case:codex-cost-limit') })
    const b = screen.getByRole('button', { name: 'Remove filter case:codex-cost-limit' })
    await userEvent.click(b)
    expect(onremove).toHaveBeenCalledOnce()
  })
  it('renders a link with href', () => {
    render(Tag, { href: '/evals?tag=x', children: text('case:x') })
    expect(screen.getByRole('link', { name: 'case:x' })).toBeTruthy()
  })
})
