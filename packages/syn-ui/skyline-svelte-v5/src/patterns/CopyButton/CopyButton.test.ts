// @vitest-environment jsdom
// Copy Button over plain http (#742): no Clipboard API, so the copy must take
// writeClipboard's execCommand fallback and still report what happened.
import '../../components/_test/setup'
import { fireEvent, render, screen, waitFor } from '@testing-library/svelte'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { insecureClipboard, type InsecureClipboard } from '../../components/_test/clipboard'
import CopyButton from './CopyButton.svelte'

let clipboard: InsecureClipboard
beforeEach(() => {
  clipboard = insecureClipboard()
})
afterEach(() => clipboard.restore())

describe('Copy Button', () => {
  it('copies through the fallback when the page is not a secure context', async () => {
    const oncopied = vi.fn()
    render(CopyButton, { text: 'exec-66e14f23', label: 'Copy the execution ID', oncopied })
    await fireEvent.click(screen.getByRole('button', { name: 'Copy the execution ID' }))
    await waitFor(() => expect(oncopied).toHaveBeenCalledWith('exec-66e14f23'))
    expect(clipboard.copied).toEqual(['exec-66e14f23'])
    expect(screen.getByRole('button').dataset.state).toBe('copied')
    expect(screen.getByRole('status').textContent).toBe('Copied')
  })

  it('reports failure when the browser blocks the fallback too', async () => {
    clipboard.block()
    const onerror = vi.fn()
    render(CopyButton, { text: 'exec-66e14f23', variant: 'label', label: 'Copy ID', onerror })
    await fireEvent.click(screen.getByRole('button', { name: 'Copy ID' }))
    await waitFor(() => expect(onerror).toHaveBeenCalledOnce())
    expect(screen.getByRole('button').dataset.state).toBe('failed')
    expect(screen.getByRole('status').textContent).toBe('Copy failed')
  })
})
