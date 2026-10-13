<!-- Accordion (AccordionContract): rows in a card, each opening in place under its header. -->
<script lang="ts">
  import { untrack } from 'svelte'
  import { listMoveForKey, moveIndex, toggleValue } from '@syn137/skyline-core/state'
  import Glyph from '../_internal/Glyph.svelte'
  import type { AccordionProps } from './types'

  let {
    type,
    items,
    value = $bindable(),
    defaultValue = [],
    onValueChange,
    collapsible = true,
    disabled = false,
    level = 3,
    children,
    ...rest
  }: AccordionProps = $props()

  const uid = $props.id()
  let internal = $state<string[]>(untrack(() => [...defaultValue]))
  const openValues = $derived(value ?? internal)
  const disabledList = $derived(items.map((i) => disabled || !!i.disabled))
  let refs: HTMLButtonElement[] = $state([])

  function toggle(v: string) {
    const next = toggleValue(openValues, v, type, type === 'single' ? collapsible : true)
    internal = next
    if (value !== undefined) value = next
    onValueChange?.(next)
  }

  function onKeydown(e: KeyboardEvent, i: number) {
    const move = listMoveForKey(e.key, 'vertical')
    if (!move) return
    e.preventDefault()
    const next = moveIndex(i, move, disabledList)
    if (next >= 0) refs[next]?.focus()
  }
</script>

<div {...rest} class="sky-accordion">
  {#each items as item, i (item.value)}
    {@const isOpen = openValues.includes(item.value)}
    {@const locked = isOpen && type === 'single' && !collapsible}
    <div class="sky-accordion__item" data-state={isOpen ? 'open' : 'closed'}>
      <svelte:element this={`h${level}`} class="sky-accordion__heading">
        <button
          bind:this={refs[i]}
          type="button"
          class="sky-accordion__trigger"
          id={`${uid}-trigger-${i}`}
          aria-expanded={isOpen}
          aria-controls={`${uid}-panel-${i}`}
          aria-disabled={locked || undefined}
          disabled={disabledList[i]}
          onclick={() => toggle(item.value)}
          onkeydown={(e) => onKeydown(e, i)}
        >
          <span class="sky-accordion__title">{item.title}</span>
          {#if item.meta}<span class="sky-accordion__meta">{item.meta}</span>{/if}
          <span class="sky-accordion__chevron"><Glyph name="chevron-down" size={16} strokeWidth={1.75} /></span>
        </button>
      </svelte:element>
      <div class="sky-accordion__panel" id={`${uid}-panel-${i}`} role="region" aria-labelledby={`${uid}-trigger-${i}`} hidden={!isOpen}>
        {@render children?.(item)}
      </div>
    </div>
  {/each}
</div>

<style>
  .sky-accordion {
    display: flex;
    flex-direction: column;
    min-width: 0;
    border: var(--ds-border-width) solid var(--ds-color-border);
    border-radius: var(--sky-radius-row);
    background: var(--ds-color-surface);
    overflow: hidden;
  }
  .sky-accordion__item + .sky-accordion__item {
    border-top: var(--ds-border-width) solid var(--sky-color-divider);
  }
  .sky-accordion__heading {
    margin: 0;
    font: inherit;
  }
  .sky-accordion__trigger {
    display: flex;
    align-items: center;
    gap: var(--ds-space-3);
    width: 100%;
    min-height: var(--sky-size-touch);
    padding: var(--ds-space-2) var(--ds-space-3-5);
    border: 0;
    background: transparent;
    color: var(--ds-color-fg);
    font-family: inherit;
    font-size: var(--ds-text-md);
    text-align: left;
    cursor: pointer;
    -webkit-tap-highlight-color: transparent;
  }
  .sky-accordion__trigger:hover:not(:disabled) {
    background: var(--sky-color-control-hover);
  }
  .sky-accordion__trigger:disabled {
    opacity: 0.4;
    cursor: not-allowed;
  }
  .sky-accordion__trigger:focus-visible {
    outline: var(--sky-focus-ring-width) solid var(--sky-color-focus);
    outline-offset: calc(var(--sky-focus-ring-width) * -1);
  }
  .sky-accordion__title {
    flex: 1 1 auto;
    min-width: 0;
    overflow-wrap: anywhere;
  }
  .sky-accordion__meta {
    flex-shrink: 0;
    font-family: var(--ds-font-mono);
    font-size: var(--ds-text-xs);
    color: var(--ds-color-text-subtle);
  }
  .sky-accordion__chevron {
    display: flex;
    flex-shrink: 0;
    color: var(--ds-color-text-muted);
    transition: transform var(--sky-duration-base) var(--sky-ease-out);
  }
  .sky-accordion__item[data-state='open'] .sky-accordion__chevron {
    transform: rotate(180deg);
  }
  .sky-accordion__panel {
    padding: 0 var(--ds-space-3-5) var(--ds-space-3-5);
    font-size: var(--ds-text-sm);
    color: var(--ds-color-text-muted);
  }
</style>
