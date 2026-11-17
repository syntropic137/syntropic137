// @vitest-environment jsdom
// Agent Prompt Button over plain http (#742): the prompt still reaches the
// clipboard through writeClipboard's fallback, and a blocked copy says so.
import '../../components/_test/setup'
import { fireEvent, render, screen, waitFor } from '@testing-library/svelte'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { insecureClipboard, type InsecureClipboard } from '../../components/_test/clipboard'
import AgentPromptButton from './AgentPromptButton.svelte'

const PROMPT = 'Run the research workflow: syn workflow run research --input topic=clipboards'

let clipboard: InsecureClipboard
beforeEach(() => {
  clipboard = insecureClipboard()
})
afterEach(() => clipboard.restore())

describe('Agent Prompt Button', () => {
  it('copies the prompt through the fallback when the page is not a secure context', async () => {
    const oncopied = vi.fn()
    render(AgentPromptButton, { prompt: PROMPT, oncopied })
    await fireEvent.click(screen.getByRole('button', { name: 'Copy agent prompt' }))
    await waitFor(() => expect(oncopied).toHaveBeenCalledWith(PROMPT))
    expect(clipboard.copied).toEqual([PROMPT])
    expect(screen.getByRole('button').dataset.state).toBe('copied')
    expect(screen.getByRole('status').textContent?.trim()).toBe('Paste it into your agent to start a run.')
  })

  it('reports failure when the browser blocks the fallback too', async () => {
    clipboard.block()
    render(AgentPromptButton, { prompt: PROMPT })
    await fireEvent.click(screen.getByRole('button', { name: 'Copy agent prompt' }))
    await waitFor(() => expect(screen.getByRole('button').dataset.state).toBe('failed'))
    expect(screen.getByRole('status').textContent?.trim()).toBe('Copy failed: the browser blocked the clipboard.')
  })
})
