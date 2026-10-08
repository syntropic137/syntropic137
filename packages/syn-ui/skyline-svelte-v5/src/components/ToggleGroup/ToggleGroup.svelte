<!--
  Toggle Group (ToggleGroupContract). CompActions: segmented, segmented mono,
  and filter chips with counts. Roving tabindex: Tab enters and leaves the
  group, arrows move inside it.
-->
<script lang="ts">
  import { untrack } from 'svelte'
  import { listMoveForKey, moveIndex, toggleValue } from '@syn137/skyline-core/state'
  import type { ToggleGroupProps } from './types'

  let {
    type,
    items,
    value = $bindable(),
    defaultValue = [],
    onValueChange,
    orientation = 'horizontal',
    size = 'md',
    disabled = false,
    variant = 'segmented',
    mono = false,
    allowEmpty = false,
    ...rest
  }: ToggleGroupProps = $props()

  let internal = $state<string[]>(untrack(() => [...defaultValue]))
  const selected = $derived(value ?? internal)
  let refs: HTMLButtonElement[] = $state([])
  let focusIndex = $state(-1)

  const single = $derived(type === 'single')
  const disabledList = $derived(items.map((i) => disabled || !!i.disabled))
  /** The item that takes Tab focus: the focused one, else the first selected, else the first enabled. */
  const tabStop = $derived.by(() => {
    if (focusIndex >= 0 && !disabledList[focusIndex]) return focusIndex
    const sel = items.findIndex((it, i) => selected.includes(it.value) && !disabledList[i])
    return sel >= 0 ? sel : moveIndex(-1, 'first', disabledList)
  })

  function commit(next: string[]) {
    internal = next
    if (value !== undefined) value = next
    onValueChange?.(next)
  }

  function activate(i: number) {
    const item = items[i]
    if (!item || disabledList[i]) return
    const next = toggleValue(selected, item.value, type, single ? allowEmpty : true)
    if (next.length === selected.length && next.every((v, k) => v === selected[k])) return
    commit(next)
  }

  function onKeydown(e: KeyboardEvent, i: number) {
    const move = listMoveForKey(e.key, orientation)
    if (!move) return
    e.preventDefault()
    const next = moveIndex(i, move, disabledList)
    if (next < 0) return
    focusIndex = next
    refs[next]?.focus()
    if (single && !selected.includes(items[next]!.value)) commit([items[next]!.value])
  }
</script>

<div
  {...rest}
  class="sky-toggle-group"
  role={single ? 'radiogroup' : 'group'}
  aria-orientation={orientation}
  aria-disabled={disabled || undefined}
  data-variant={variant}
  data-size={size}
  data-orientation={orientation}
  data-mono={mono || undefined}
>
  {#each items as item, i (item.value)}
    {@const on = selected.includes(item.value)}
    <button
      bind:this={refs[i]}
      type="button"
      class="sky-toggle-group__item"
      role={single ? 'radio' : undefined}
      aria-checked={single ? on : undefined}
      aria-pressed={single ? undefined : on}
      data-state={on ? 'on' : 'off'}
      disabled={disabledList[i]}
      tabindex={i === tabStop ? 0 : -1}
      onclick={() => {
        focusIndex = i
        activate(i)
      }}
      onkeydown={(e) => onKeydown(e, i)}
      onfocus={() => (focusIndex = i)}
    >
      <span class="sky-toggle-group__label">{item.label}</span>
      {#if item.count !== undefined}<span class="sky-toggle-group__count">{item.count}</span>{/if}
    </button>
  {/each}
</div>

<style>
  .sky-toggle-group {
    display: inline-flex;
    max-width: 100%;
    box-sizing: border-box;
  }
  .sky-toggle-group[data-orientation='vertical'] {
    flex-direction: column;
  }
  .sky-toggle-group__item {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    gap: var(--ds-space-2);
    flex-shrink: 0;
    box-sizing: border-box;
    padding: 0 var(--ds-space-3-5);
    border: 0;
    background: transparent;
    color: var(--ds-color-text-muted);
    font-family: inherit;
    font-size: var(--ds-text-sm);
    white-space: nowrap;
    cursor: pointer;
    -webkit-tap-highlight-color: transparent;
    transition:
      background-color var(--sky-duration-fast) var(--sky-ease-out),
      border-color var(--sky-duration-fast) var(--sky-ease-out),
      color var(--sky-duration-fast) var(--sky-ease-out);
  }
  .sky-toggle-group[data-mono] .sky-toggle-group__item {
    font-family: var(--ds-font-mono);
    font-size: var(--sky-text-data);
  }
  .sky-toggle-group__count {
    font-family: var(--ds-font-mono);
    font-size: 0.71875rem;
    color: var(--ds-color-text-muted);
  }
  .sky-toggle-group__item:hover:not(:disabled) {
    color: var(--ds-color-fg);
  }
  .sky-toggle-group__item:disabled {
    opacity: 0.4;
    cursor: not-allowed;
  }
  .sky-toggle-group__item:focus-visible {
    outline: var(--sky-focus-ring-width) solid var(--sky-color-focus);
    outline-offset: var(--sky-focus-ring-offset);
  }

  /* ---- Segmented ---- */
  .sky-toggle-group[data-variant='segmented'] {
    gap: var(--ds-space-0-5);
    padding: 3px;
    border: var(--ds-border-width) solid var(--sky-color-border-muted);
    border-radius: var(--sky-radius-control);
    background: var(--ds-color-bg);
    overflow-x: auto;
    scrollbar-width: none;
  }
  .sky-toggle-group[data-variant='segmented'] .sky-toggle-group__item {
    height: 1.875rem; /* 30 */
    border-radius: var(--ds-radius-sm);
  }
  .sky-toggle-group[data-variant='segmented'][data-size='sm'] .sky-toggle-group__item {
    height: 1.5rem;
    padding: 0 var(--ds-space-2-5);
  }
  .sky-toggle-group[data-variant='segmented'][data-size='lg'] .sky-toggle-group__item {
    height: 2.375rem;
  }
  .sky-toggle-group[data-variant='segmented'] .sky-toggle-group__item[data-state='on'] {
    background: var(--ds-color-overlay);
    color: var(--ds-color-fg);
    box-shadow: var(--sky-shadow-selected);
  }

  /* ---- Chips: one sideways-scrolling row on a phone, wrapping from 48rem ---- */
  .sky-toggle-group[data-variant='chips'] {
    display: flex;
    gap: var(--ds-space-2);
    overflow-x: auto;
    overscroll-behavior-x: contain;
    scrollbar-width: none;
    /* Room for the focus ring inside the scroller. */
    padding: var(--sky-focus-ring-width);
    margin: calc(var(--sky-focus-ring-width) * -1);
  }
  .sky-toggle-group[data-variant='chips']::-webkit-scrollbar,
  .sky-toggle-group[data-variant='segmented']::-webkit-scrollbar {
    display: none;
  }
  .sky-toggle-group[data-variant='chips'] .sky-toggle-group__item {
    height: var(--sky-size-nav-item);
    border: var(--ds-border-width) solid var(--sky-color-border-muted);
    border-radius: var(--ds-radius-full);
  }
  .sky-toggle-group[data-variant='chips'][data-size='sm'] .sky-toggle-group__item {
    height: 1.75rem;
    padding: 0 var(--ds-space-3);
  }
  .sky-toggle-group[data-variant='chips'] .sky-toggle-group__item:hover:not(:disabled) {
    border-color: var(--sky-color-border-hover);
  }
  .sky-toggle-group[data-variant='chips'] .sky-toggle-group__item[data-state='on'] {
    border-color: var(--sky-color-border-hover);
    background: var(--ds-color-overlay);
    color: var(--ds-color-fg);
  }

  @media (min-width: 48rem) {
    .sky-toggle-group[data-variant='chips'] {
      flex-wrap: wrap;
      overflow-x: visible;
    }
  }
  @media (pointer: coarse) {
    .sky-toggle-group__item {
      min-height: var(--sky-size-touch);
    }
    .sky-toggle-group[data-variant='segmented'] .sky-toggle-group__item {
      min-height: 2.375rem;
    }
  }
</style>
