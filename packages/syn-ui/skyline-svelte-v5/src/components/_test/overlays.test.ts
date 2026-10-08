// @vitest-environment jsdom
// Popover, Dropdown Menu, Tooltip, Dialog, Alert Dialog, Command, Collapsible, Accordion, Copy Button, Breadcrumbs.
import './setup'
import { render, screen, waitFor } from '@testing-library/svelte'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import Breadcrumbs from '../Breadcrumbs/Breadcrumbs.svelte'
import Command from '../Command/Command.svelte'
import CopyButton from '../CopyButton/CopyButton.svelte'
import Meter from '../Meter/Meter.svelte'
import Progress from '../Progress/Progress.svelte'
import AccordionHarness from './AccordionHarness.svelte'
import AlertHarness from './AlertHarness.svelte'
import CollapsibleHarness from './CollapsibleHarness.svelte'
import DialogHarness from './DialogHarness.svelte'
import MenuHarness from './MenuHarness.svelte'
import PopoverHarness from './PopoverHarness.svelte'
import TooltipHarness from './TooltipHarness.svelte'

describe('Popover', () => {
  it('opens from its trigger, moves focus in, closes on Escape and returns focus', async () => {
    render(PopoverHarness)
    const trigger = screen.getByRole('button', { name: 'Status' })
    expect(trigger.getAttribute('aria-expanded')).toBe('false')
    await userEvent.click(trigger)
    const panel = screen.getByRole('dialog', { name: 'Filter by status' })
    expect(trigger.getAttribute('aria-expanded')).toBe('true')
    expect(trigger.getAttribute('aria-controls')).toBe(panel.id)
    await waitFor(() => expect(document.activeElement).toBe(screen.getByRole('button', { name: 'Completed' })))
    await userEvent.keyboard('{Escape}')
    expect(screen.queryByRole('dialog')).toBeNull()
    expect(document.activeElement).toBe(trigger)
  })
  it('closes on an outside click and through close()', async () => {
    render(PopoverHarness)
    await userEvent.click(screen.getByRole('button', { name: 'Status' }))
    await userEvent.click(screen.getByRole('button', { name: 'outside' }))
    expect(screen.queryByRole('dialog')).toBeNull()
    await userEvent.click(screen.getByRole('button', { name: 'Status' }))
    await userEvent.click(screen.getByRole('button', { name: 'Done' }))
    expect(screen.queryByRole('dialog')).toBeNull()
  })
})

describe('DropdownMenu', () => {
  const items = [
    { label: 'Evals', meta: '65' },
    { label: 'Triggers', meta: '6' },
    { type: 'separator' as const },
    { label: 'Sessions', meta: '108', disabled: true },
    { label: 'Repos', meta: '2' },
  ]

  it('opens on ArrowDown at the first item and navigates past disabled items', async () => {
    render(MenuHarness, { items })
    const trigger = screen.getByRole('button', { name: 'More' })
    expect(trigger.getAttribute('aria-haspopup')).toBe('menu')
    trigger.focus()
    await userEvent.keyboard('{ArrowDown}')
    const menu = screen.getByRole('menu', { name: 'Sections' })
    await waitFor(() => expect(document.activeElement?.textContent).toContain('Evals'))
    await userEvent.keyboard('{ArrowDown}{ArrowDown}')
    expect(document.activeElement?.textContent).toContain('Repos')
    await userEvent.keyboard('{Home}')
    expect(document.activeElement?.textContent).toContain('Evals')
    expect(menu.querySelectorAll('[role=menuitem]')).toHaveLength(4)
  })

  it('selects with Enter, closes and returns focus', async () => {
    const onSelect = vi.fn()
    render(MenuHarness, { items, onSelect })
    const trigger = screen.getByRole('button', { name: 'More' })
    await userEvent.click(trigger)
    await waitFor(() => expect(document.activeElement?.textContent).toContain('Evals'))
    await userEvent.keyboard('t')
    expect(document.activeElement?.textContent).toContain('Triggers')
    await userEvent.keyboard('{Enter}')
    expect(onSelect).toHaveBeenCalledWith(expect.objectContaining({ label: 'Triggers' }))
    expect(screen.queryByRole('menu')).toBeNull()
    expect(document.activeElement).toBe(trigger)
  })

  it('closes on Escape', async () => {
    render(MenuHarness, { items })
    await userEvent.click(screen.getByRole('button', { name: 'More' }))
    await userEvent.keyboard('{Escape}')
    expect(screen.queryByRole('menu')).toBeNull()
  })
})

describe('Tooltip', () => {
  it('describes its trigger and shows on focus, hides on Escape', async () => {
    render(TooltipHarness)
    const trigger = screen.getByRole('button', { name: '66e14f23' })
    const tip = document.getElementById(trigger.getAttribute('aria-describedby')!)!
    expect(tip.getAttribute('role')).toBe('tooltip')
    expect(tip.hidden).toBe(true)
    trigger.focus()
    await waitFor(() => expect(tip.hidden).toBe(false))
    expect(tip.textContent).toContain('exec-66e14f235942')
    await userEvent.keyboard('{Escape}')
    expect(tip.hidden).toBe(true)
  })
})

describe('Dialog', () => {
  it('opens modally with a labelled title and closes from its close button', async () => {
    const onOpenChange = vi.fn()
    render(DialogHarness, { onOpenChange })
    const trigger = screen.getByRole('button', { name: 'View transcript' })
    await userEvent.click(trigger)
    const dialog = screen.getByRole('dialog', { name: /Transcript/ })
    expect(dialog.hasAttribute('open')).toBe(true)
    expect(screen.getByText('Body')).toBeTruthy()
    await waitFor(() => expect(document.activeElement).toBe(screen.getByRole('button', { name: 'Done' })))
    await userEvent.click(screen.getByRole('button', { name: 'Close' }))
    expect(onOpenChange).toHaveBeenLastCalledWith(false)
    expect(dialog.hasAttribute('open')).toBe(false)
    expect(document.activeElement).toBe(trigger)
  })
  it('closes on the native cancel (Escape)', async () => {
    render(DialogHarness)
    await userEvent.click(screen.getByRole('button', { name: 'View transcript' }))
    const dialog = screen.getByRole('dialog')
    dialog.dispatchEvent(new Event('cancel', { cancelable: true }))
    await waitFor(() => expect(dialog.hasAttribute('open')).toBe(false))
  })
})

describe('AlertDialog', () => {
  it('focuses Cancel first and cancels', async () => {
    const onCancel = vi.fn()
    render(AlertHarness, { onCancel })
    await userEvent.click(screen.getByRole('button', { name: 'Delete' }))
    const dialog = screen.getByRole('alertdialog', { name: 'Delete this trigger?' })
    expect(dialog.getAttribute('aria-describedby')).toBeTruthy()
    await waitFor(() => expect(document.activeElement).toBe(screen.getByRole('button', { name: 'Cancel' })))
    await userEvent.click(screen.getByRole('button', { name: 'Cancel' }))
    expect(onCancel).toHaveBeenCalledOnce()
    expect(dialog.hasAttribute('open')).toBe(false)
  })
  it('waits for an async confirm and keeps the dialog open on failure', async () => {
    let fail = true
    const onConfirm = vi.fn(() => (fail ? Promise.reject(new Error('Trigger is in use')) : Promise.resolve()))
    render(AlertHarness, { onConfirm })
    await userEvent.click(screen.getByRole('button', { name: 'Delete' }))
    await userEvent.click(screen.getByRole('button', { name: 'Delete trigger' }))
    expect(await screen.findByRole('alert')).toBeTruthy()
    expect(screen.getByRole('alert').textContent).toContain('Trigger is in use')
    expect(screen.getByRole('alertdialog').hasAttribute('open')).toBe(true)
    fail = false
    await userEvent.click(screen.getByRole('button', { name: 'Delete trigger' }))
    await waitFor(() => expect(screen.getByRole('alertdialog', { hidden: true }).hasAttribute('open')).toBe(false))
  })
})

describe('Command', () => {
  const groups = [
    {
      heading: 'Workflows',
      items: [
        { id: 'wf-1', label: 'Research Workflow', meta: 'research-workflow-v2', keywords: ['research-workflow-v2'] },
        { id: 'wf-2', label: 'Research with Prompt Files', meta: 'research-with-prompts-v1' },
      ],
    },
    { heading: 'Go to', items: [{ id: 'go-evals', label: 'Evals', shortcut: 'G E' }] },
  ]

  it('filters, moves the active option and selects with Enter', async () => {
    const onSelect = vi.fn()
    render(Command, { groups, onSelect })
    const input = screen.getByRole('combobox')
    expect(screen.getAllByRole('option')).toHaveLength(3)
    await userEvent.type(input, 'resea')
    expect(screen.getAllByRole('option')).toHaveLength(2)
    expect(screen.queryByText('Evals')).toBeNull()
    const first = screen.getAllByRole('option')[0]!
    expect(input.getAttribute('aria-activedescendant')).toBe(first.id)
    await userEvent.keyboard('{ArrowDown}')
    expect(input.getAttribute('aria-activedescendant')).toBe(screen.getAllByRole('option')[1]!.id)
    await userEvent.keyboard('{Enter}')
    expect(onSelect).toHaveBeenCalledWith(expect.objectContaining({ id: 'wf-2' }))
  })

  it('says when nothing matches', async () => {
    render(Command, { groups, empty: 'Nothing found.' })
    await userEvent.type(screen.getByRole('combobox'), 'zzzz')
    expect(screen.getByText('Nothing found.')).toBeTruthy()
  })
})

describe('Collapsible', () => {
  it('toggles aria-expanded and the content', async () => {
    const onOpenChange = vi.fn()
    render(CollapsibleHarness, { onOpenChange })
    const trigger = screen.getByRole('button', { name: /Outline/ })
    const content = document.getElementById(trigger.getAttribute('aria-controls')!)!
    expect(content.hidden).toBe(true)
    await userEvent.click(trigger)
    expect(trigger.getAttribute('aria-expanded')).toBe('true')
    expect(content.hidden).toBe(false)
    expect(onOpenChange).toHaveBeenLastCalledWith(true)
  })
})

describe('Accordion', () => {
  it('single: opens one at a time; arrows move between headers', async () => {
    render(AccordionHarness)
    const a = screen.getByRole('button', { name: 'check_run.completed' })
    const c = screen.getByRole('button', { name: 'push' })
    await userEvent.click(a)
    expect(a.getAttribute('aria-expanded')).toBe('true')
    expect(screen.getByRole('region', { name: 'check_run.completed' }).textContent).toContain('Rule for check_run.completed')
    await userEvent.click(c)
    expect(a.getAttribute('aria-expanded')).toBe('false')
    expect(c.getAttribute('aria-expanded')).toBe('true')
    a.focus()
    await userEvent.keyboard('{ArrowDown}')
    expect(document.activeElement).toBe(c)
  })
  it('single without collapsible keeps the open item open', async () => {
    render(AccordionHarness, { collapsible: false })
    const a = screen.getByRole('button', { name: 'check_run.completed' })
    await userEvent.click(a)
    await userEvent.click(a)
    expect(a.getAttribute('aria-expanded')).toBe('true')
  })
  it('multiple: keeps several open', async () => {
    render(AccordionHarness, { type: 'multiple' })
    const a = screen.getByRole('button', { name: 'check_run.completed' })
    const c = screen.getByRole('button', { name: 'push' })
    await userEvent.click(a)
    await userEvent.click(c)
    expect(a.getAttribute('aria-expanded')).toBe('true')
    expect(c.getAttribute('aria-expanded')).toBe('true')
  })
})

describe('CopyButton', () => {
  it('copies, flips to the copied state and announces it', async () => {
    const user = userEvent.setup()
    const onCopy = vi.fn()
    render(CopyButton, { label: 'Copy all', text: 'hello', onCopy })
    await user.click(screen.getByRole('button', { name: 'Copy all' }))
    await waitFor(() => expect(onCopy).toHaveBeenCalledWith('hello'))
    expect(await navigator.clipboard.readText()).toBe('hello')
    expect(screen.getByRole('button').dataset.state).toBe('copied')
    expect(screen.getByRole('button').textContent).toContain('Copied all')
    expect(screen.getByRole('status').textContent).toBe('Copied all')
  })
  it('is an icon button named Copy without a label', () => {
    render(CopyButton, { text: 'x' })
    expect(screen.getByRole('button', { name: 'Copy' }).dataset.iconOnly).toBe('true')
  })
})

describe('Breadcrumbs', () => {
  const items = [{ label: 'Workflows', href: '/workflows' }, { label: 'Research Workflow', href: '/workflows/1' }, { label: 'Execution', id: '66e14f23' }]
  it('marks the current page and reveals the hidden middle', async () => {
    render(Breadcrumbs, { items, homeHref: '/' })
    expect(screen.getByRole('link', { name: 'Overview' }).getAttribute('href')).toBe('/')
    const current = screen.getByText(/Execution/)
    expect(current.closest('[aria-current]')?.getAttribute('aria-current')).toBe('page')
    const more = screen.getByRole('button', { name: 'Show the full path' })
    await userEvent.click(more)
    expect(screen.getByRole('navigation').dataset.expanded).toBe('true')
  })
})

describe('Meter and Progress', () => {
  it('exposes meter values and its label', () => {
    render(Meter, { label: 'Codex delegates to Claude', valueText: '26 runs', value: 26, max: 26 })
    const meter = screen.getByRole('meter', { name: 'Codex delegates to Claude' })
    expect(meter.getAttribute('aria-valuenow')).toBe('26')
    expect(meter.getAttribute('aria-valuetext')).toBe('26 runs')
  })
  it('fills phase blocks and omits valuenow when indeterminate', () => {
    const { container } = render(Progress, { value: 1.45, segments: 3, valueText: 'phase 2 of 3', 'aria-label': 'Run progress' })
    const fills = [...container.querySelectorAll<HTMLElement>('.sky-progress__fill')].map((f) => f.style.width)
    expect(fills).toEqual(['100%', '45%', '0%'])
    render(Progress, { value: null, 'aria-label': 'Starting' })
    expect(screen.getByRole('progressbar', { name: 'Starting' }).hasAttribute('aria-valuenow')).toBe(false)
  })
})
