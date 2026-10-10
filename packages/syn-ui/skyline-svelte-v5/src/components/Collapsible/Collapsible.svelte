<!-- Collapsible (CollapsibleRootContract). CompNav "collapsible": "Outline · 2 sections" with a chevron. -->
<script lang="ts">
  import { untrack } from 'svelte'
  import Glyph from '../_internal/Glyph.svelte'
  import type { CollapsibleProps, CollapsibleTriggerProps } from './types'

  let {
    open = $bindable(),
    defaultOpen = false,
    onOpenChange,
    disabled = false,
    title,
    meta,
    trigger,
    variant = 'card',
    children,
    ...rest
  }: CollapsibleProps = $props()

  const uid = $props.id()
  const contentId = `${uid}-content`
  let internal = $state(untrack(() => defaultOpen))
  const isOpen = $derived(open ?? internal)

  function toggle() {
    if (disabled) return
    const next = !isOpen
    internal = next
    if (open !== undefined) open = next
    onOpenChange?.(next)
  }

  const triggerProps: CollapsibleTriggerProps = $derived({
    'aria-expanded': isOpen,
    'aria-controls': contentId,
    'data-state': isOpen ? 'open' : 'closed',
    disabled,
    onclick: toggle,
  })
</script>

<div {...rest} class="sky-collapsible" data-variant={variant} data-state={isOpen ? 'open' : 'closed'}>
  {#if trigger}
    {@render trigger(triggerProps)}
  {:else}
    <button type="button" class="sky-collapsible__trigger" {...triggerProps}>
      <span class="sky-collapsible__title">
        {title}{#if meta}<span class="sky-collapsible__meta">{meta}</span>{/if}
      </span>
      <span class="sky-collapsible__chevron"><Glyph name="chevron-down" size={16} strokeWidth={1.75} /></span>
    </button>
  {/if}
  <div class="sky-collapsible__content" id={contentId} hidden={!isOpen}>
    {@render children?.()}
  </div>
</div>

<style>
  .sky-collapsible {
    display: flex;
    flex-direction: column;
    min-width: 0;
  }
  .sky-collapsible[data-variant='card'] {
    border: var(--ds-border-width) solid var(--ds-color-border);
    border-radius: var(--sky-radius-row);
    background: var(--ds-color-surface);
    overflow: hidden;
  }
  .sky-collapsible__trigger {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: var(--ds-space-3);
    min-height: var(--sky-size-touch);
    padding: 0 var(--ds-space-3-5);
    border: 0;
    background: transparent;
    color: var(--ds-color-fg);
    font-family: inherit;
    font-size: var(--ds-text-md);
    text-align: left;
    cursor: pointer;
    -webkit-tap-highlight-color: transparent;
  }
  .sky-collapsible[data-variant='plain'] .sky-collapsible__trigger {
    padding: 0;
  }
  .sky-collapsible__trigger:hover:not(:disabled) {
    background: var(--sky-color-control-hover);
  }
  .sky-collapsible[data-variant='plain'] .sky-collapsible__trigger:hover:not(:disabled) {
    background: transparent;
    color: var(--ds-color-accent-hover);
  }
  .sky-collapsible__trigger:disabled {
    opacity: 0.4;
    cursor: not-allowed;
  }
  .sky-collapsible__trigger:focus-visible {
    outline: var(--sky-focus-ring-width) solid var(--sky-color-focus);
    outline-offset: calc(var(--sky-focus-ring-width) * -1);
  }
  .sky-collapsible__title {
    display: flex;
    align-items: baseline;
    gap: var(--ds-space-2);
    min-width: 0;
  }
  .sky-collapsible__meta {
    font-family: var(--ds-font-mono);
    font-size: var(--ds-text-xs);
    color: var(--ds-color-text-subtle);
  }
  .sky-collapsible__chevron {
    display: flex;
    flex-shrink: 0;
    color: var(--ds-color-text-muted);
    transition: transform var(--sky-duration-base) var(--sky-ease-out);
  }
  .sky-collapsible[data-state='open'] .sky-collapsible__chevron {
    transform: rotate(180deg);
  }
  .sky-collapsible[data-variant='card'][data-state='open'] .sky-collapsible__trigger {
    border-bottom: var(--ds-border-width) solid var(--ds-color-border);
  }
  .sky-collapsible[data-variant='card'] .sky-collapsible__content {
    padding: var(--ds-space-2-5) var(--ds-space-3-5);
    font-size: var(--ds-text-sm);
    color: var(--ds-color-text-muted);
  }
  .sky-collapsible[data-variant='plain'] .sky-collapsible__content {
    padding-top: var(--ds-space-2);
  }
</style>
