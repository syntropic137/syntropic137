<!-- Copy Button (CompActions): idle copy glyph, then an accent check on a soft fill. -->
<script lang="ts">
  import { COPY_FEEDBACK_MS, copyFeedback, type CopyEvent, type CopyState } from '@syn137/skyline-core/state'
  import Glyph from '../_internal/Glyph.svelte'
  import { writeClipboard } from './clipboard'
  import type { CopyButtonProps } from './types'

  let {
    text,
    getText,
    label,
    copiedLabel,
    size = 'sm',
    onCopy,
    onError,
    onclick,
    'aria-label': ariaLabel,
    ...rest
  }: CopyButtonProps = $props()

  let copyState = $state<CopyState>('idle')
  let timer: ReturnType<typeof setTimeout> | undefined
  const send = (event: CopyEvent) => (copyState = copyFeedback(copyState, event))
  const doneLabel = $derived(copiedLabel ?? (label ? label.replace(/^Copy\b/, 'Copied') : 'Copied'))
  const announce = $derived(copyState === 'copied' ? doneLabel : copyState === 'failed' ? 'Copy failed' : '')

  async function copy(e: MouseEvent & { currentTarget: EventTarget & HTMLButtonElement }) {
    onclick?.(e)
    if (e.defaultPrevented || copyState === 'copying') return
    send({ type: 'copy' })
    try {
      const value = getText ? await getText() : (text ?? '')
      await writeClipboard(value)
      send({ type: 'success' })
      onCopy?.(value)
    } catch (err) {
      send({ type: 'error' })
      onError?.(err)
    }
    clearTimeout(timer)
    timer = setTimeout(() => send({ type: 'reset' }), COPY_FEEDBACK_MS)
  }

  $effect(() => () => clearTimeout(timer))
</script>

<span class="sky-copy">
  <button
    {...rest}
    type="button"
    class="sky-copy__button"
    data-state={copyState}
    data-size={size}
    data-icon-only={!label || undefined}
    aria-label={label ? undefined : (ariaLabel ?? 'Copy')}
    onclick={copy}
  >
    <Glyph name={copyState === 'copied' ? 'check' : copyState === 'failed' ? 'cross' : 'copy'} size={15} strokeWidth={1.6} />
    {#if label}<span>{copyState === 'copied' ? doneLabel : label}</span>{/if}
  </button>
  <span class="sky-visually-hidden" role="status">{announce}</span>
</span>

<style>
  .sky-copy {
    display: contents;
  }
  .sky-copy__button {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    gap: var(--ds-space-2);
    flex-shrink: 0;
    box-sizing: border-box;
    height: var(--sky-size-control-sm);
    padding: 0 var(--ds-space-3);
    border: 0;
    border-radius: var(--ds-radius-md);
    background: transparent;
    color: var(--ds-color-text-muted);
    font-family: inherit;
    font-size: var(--sky-text-data);
    white-space: nowrap;
    cursor: pointer;
    -webkit-tap-highlight-color: transparent;
    transition:
      background-color var(--sky-duration-fast) var(--sky-ease-out),
      color var(--sky-duration-fast) var(--sky-ease-out);
  }
  .sky-copy__button[data-icon-only] {
    width: var(--sky-size-control-sm);
    padding: 0;
    border-radius: var(--ds-radius-sm);
  }
  .sky-copy__button[data-size='xs'] {
    height: 1.875rem;
  }
  .sky-copy__button[data-size='xs'][data-icon-only] {
    width: 1.875rem;
  }
  .sky-copy__button:hover {
    background: var(--sky-color-control-hover);
    color: var(--ds-color-fg);
  }
  .sky-copy__button[data-state='copied'] {
    background: var(--sky-color-control-hover);
    color: var(--ds-color-accent);
  }
  .sky-copy__button[data-state='failed'] {
    color: var(--sky-color-danger-soft-fg);
  }
  .sky-copy__button:focus-visible {
    outline: var(--sky-focus-ring-width) solid var(--sky-color-focus);
    outline-offset: var(--sky-focus-ring-offset);
  }
  @media (pointer: coarse) {
    .sky-copy__button {
      min-height: var(--sky-size-touch);
    }
    .sky-copy__button[data-icon-only] {
      min-width: var(--sky-size-touch);
    }
  }
</style>
