<!--
  Copy Button (Session board, CompPatterns): copies a part (input, output)
  or a whole list, then flips to a check for a moment. State from the
  copyFeedback reducer in skyline-core; the timer lives here.
-->
<script lang="ts">
  import { onDestroy } from 'svelte'
  import { GLYPH } from '@syn137/skyline-core/patterns'
  import { COPY_FEEDBACK_MS, copyFeedback, type CopyEvent, type CopyState } from '@syn137/skyline-core/state'
  import Glyph from '../Glyph/Glyph.svelte'
  import type { CopyButtonProps } from './types'

  let { text, label = 'Copy', copiedLabel = 'Copied', variant = 'icon', oncopied, onerror, disabled, ...rest }: CopyButtonProps = $props()

  let status = $state<CopyState>('idle')
  let timer: ReturnType<typeof setTimeout> | undefined

  function send(e: CopyEvent) {
    status = copyFeedback(status, e)
    if (status === 'copied' || status === 'failed') {
      clearTimeout(timer)
      timer = setTimeout(() => send({ type: 'reset' }), COPY_FEEDBACK_MS)
    }
  }

  async function copy() {
    const value = typeof text === 'function' ? text() : text
    send({ type: 'copy' })
    try {
      await navigator.clipboard.writeText(value)
      send({ type: 'success' })
      oncopied?.(value)
    } catch (err) {
      send({ type: 'error' })
      onerror?.(err)
    }
  }

  onDestroy(() => clearTimeout(timer))

  const current = $derived(status === 'copied' ? copiedLabel : status === 'failed' ? 'Copy failed' : label)
</script>

<button
  {...rest}
  class="sky-copy"
  type="button"
  data-variant={variant}
  data-state={status}
  aria-label={variant === 'icon' ? current : undefined}
  disabled={disabled || status === 'copying'}
  onclick={copy}
>
  {#if variant === 'icon'}
    <Glyph d={status === 'copied' ? GLYPH.check : GLYPH.copy} size={14} weight={1.5} />
  {:else}
    {current}
  {/if}
</button>
<span class="sky-visually-hidden" role="status">{status === 'copied' ? copiedLabel : status === 'failed' ? 'Copy failed' : ''}</span>

<style>
  .sky-copy {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    flex-shrink: 0;
    padding: 0;
    border: 0;
    border-radius: var(--ds-radius-sm);
    background: transparent;
    color: var(--ds-color-text-muted);
    font: inherit;
    cursor: pointer;
  }
  .sky-copy[data-variant='icon'] {
    width: 1.75rem;
    height: 1.75rem;
  }
  .sky-copy[data-variant='label'] {
    height: var(--sky-size-control-sm);
    padding: 0 var(--ds-space-2-5);
    border-radius: var(--ds-radius-md);
    font-size: var(--sky-text-data);
  }
  .sky-copy:hover:not(:disabled) {
    background: var(--sky-color-control-hover);
    color: var(--ds-color-fg);
  }
  .sky-copy[data-state='copied'] {
    color: var(--ds-color-accent);
  }
  .sky-copy[data-state='copied'][data-variant='icon'] {
    background: var(--sky-color-control-hover);
  }
  .sky-copy[data-state='failed'] {
    color: var(--sky-color-danger-soft-fg);
  }
  .sky-copy:focus-visible {
    outline: var(--sky-focus-ring-width) solid var(--sky-color-focus);
    outline-offset: var(--sky-focus-ring-offset);
  }
  @media (pointer: coarse) {
    .sky-copy[data-variant='icon'],
    .sky-copy[data-variant='label'] {
      min-width: var(--sky-size-touch);
      min-height: var(--sky-size-touch);
    }
  }
</style>
