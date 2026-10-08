<!--
  Tabs (TabsRootContract). Segmented tab list (CompActions "segmented") over
  one tab panel. Arrow keys move between tabs; `activationMode="manual"`
  waits for Enter or Space.
-->
<script lang="ts">
  import { untrack } from 'svelte'
  import { listMoveForKey, moveIndex } from '@syn137/skyline-core/state'
  import type { TabsProps } from './types'

  let {
    items,
    value = $bindable(),
    defaultValue,
    onValueChange,
    orientation = 'horizontal',
    activationMode = 'automatic',
    label,
    mono = false,
    actions,
    children,
    ...rest
  }: TabsProps = $props()

  const uid = $props.id()
  let internal = $state(untrack(() => defaultValue ?? items.find((i) => !i.disabled)?.value ?? ''))
  const active = $derived(value ?? internal)
  const disabledList = $derived(items.map((i) => !!i.disabled))
  let refs: HTMLButtonElement[] = $state([])

  const tabId = (v: string) => `${uid}-tab-${v}`
  const panelId = `${uid}-panel`

  function select(v: string) {
    if (v === active) return
    internal = v
    if (value !== undefined) value = v
    onValueChange?.(v)
  }

  function onKeydown(e: KeyboardEvent, i: number) {
    const move = listMoveForKey(e.key, orientation)
    if (!move) return
    e.preventDefault()
    const next = moveIndex(i, move, disabledList)
    if (next < 0) return
    refs[next]?.focus()
    if (activationMode === 'automatic') select(items[next]!.value)
  }
</script>

<div {...rest} class="sky-tabs" data-orientation={orientation}>
  <div class="sky-tabs__row">
    <div class="sky-tabs__list" role="tablist" aria-label={label} aria-orientation={orientation} data-mono={mono || undefined}>
      {#each items as item, i (item.value)}
        {@const selected = item.value === active}
        <button
          bind:this={refs[i]}
          type="button"
          role="tab"
          class="sky-tabs__tab"
          id={tabId(item.value)}
          aria-selected={selected}
          aria-controls={panelId}
          data-state={selected ? 'active' : 'inactive'}
          tabindex={selected ? 0 : -1}
          disabled={item.disabled}
          onclick={() => select(item.value)}
          onkeydown={(e) => onKeydown(e, i)}
        >
          {item.label}
        </button>
      {/each}
    </div>
    {#if actions}<div class="sky-tabs__actions">{@render actions()}</div>{/if}
  </div>
  {#if children}
    <div class="sky-tabs__panel" role="tabpanel" id={panelId} aria-labelledby={tabId(active)} tabindex="0">
      {@render children(active)}
    </div>
  {/if}
</div>

<style>
  .sky-tabs {
    display: flex;
    flex-direction: column;
    gap: var(--ds-space-3);
    min-width: 0;
  }
  .sky-tabs__row {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    justify-content: space-between;
    gap: var(--ds-space-2);
  }
  .sky-tabs__actions {
    display: flex;
    align-items: center;
    gap: var(--ds-space-1);
  }
  .sky-tabs__list {
    display: inline-flex;
    gap: var(--ds-space-0-5);
    max-width: 100%;
    padding: 3px;
    box-sizing: border-box;
    border: var(--ds-border-width) solid var(--sky-color-border-muted);
    border-radius: var(--sky-radius-control);
    background: var(--ds-color-bg);
    overflow-x: auto;
    scrollbar-width: none;
  }
  .sky-tabs[data-orientation='vertical'] .sky-tabs__list {
    flex-direction: column;
  }
  .sky-tabs__tab {
    flex-shrink: 0;
    height: 1.875rem;
    padding: 0 var(--ds-space-3-5);
    border: 0;
    border-radius: var(--ds-radius-sm);
    background: transparent;
    color: var(--ds-color-text-muted);
    font-family: inherit;
    font-size: var(--ds-text-sm);
    white-space: nowrap;
    cursor: pointer;
    -webkit-tap-highlight-color: transparent;
  }
  .sky-tabs__list[data-mono] .sky-tabs__tab {
    font-family: var(--ds-font-mono);
    font-size: var(--sky-text-data);
  }
  .sky-tabs__tab:hover:not(:disabled) {
    color: var(--ds-color-fg);
  }
  .sky-tabs__tab[aria-selected='true'] {
    background: var(--ds-color-overlay);
    color: var(--ds-color-fg);
    box-shadow: var(--sky-shadow-selected);
  }
  .sky-tabs__tab:disabled {
    opacity: 0.4;
    cursor: not-allowed;
  }
  .sky-tabs__tab:focus-visible {
    outline: var(--sky-focus-ring-width) solid var(--sky-color-focus);
    outline-offset: var(--sky-focus-ring-offset);
  }
  .sky-tabs__panel {
    min-width: 0;
    border-radius: var(--sky-radius-control);
  }
  .sky-tabs__panel:focus-visible {
    outline: var(--sky-focus-ring-width) solid var(--sky-color-focus);
    outline-offset: var(--sky-focus-ring-offset);
  }
  @media (pointer: coarse) {
    .sky-tabs__tab {
      min-height: 2.375rem;
    }
  }
</style>
