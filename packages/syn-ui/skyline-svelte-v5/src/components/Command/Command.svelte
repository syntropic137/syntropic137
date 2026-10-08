<!-- Command (CommandRootContract): search input as a combobox over grouped options. -->
<script lang="ts">
  import { untrack } from 'svelte'
  import { filterCommandGroups, moveIndex } from '@syn137/skyline-core/state'
  import Glyph from '../_internal/Glyph.svelte'
  import type { CommandItem, CommandProps } from './types'

  let {
    groups,
    search = $bindable(),
    onSearchChange,
    value = $bindable(),
    defaultValue,
    onValueChange,
    shouldFilter = true,
    placeholder = 'Search or jump to…',
    empty = 'No results.',
    loading = false,
    escHint = false,
    onSelect,
    onNavigate = (href: string) => location.assign(href),
    'aria-label': ariaLabel = 'Command',
    ...rest
  }: CommandProps = $props()

  const uid = $props.id()
  const listId = `${uid}-list`
  let internalSearch = $state('')
  const query = $derived(search ?? internalSearch)
  const shown = $derived(shouldFilter ? filterCommandGroups(groups, query) : groups.filter((g) => g.items.length))
  const flat = $derived(shown.flatMap((g) => g.items))
  const disabledList = $derived(flat.map((i) => !!i.disabled))

  let internalActive = $state(untrack(() => defaultValue ?? ''))
  const requested = $derived(value ?? internalActive)
  /** The active row: the requested one if it is still shown, else the first enabled. */
  const activeIndex = $derived.by(() => {
    const i = flat.findIndex((it) => it.id === requested && !it.disabled)
    return i >= 0 ? i : moveIndex(-1, 'first', disabledList)
  })
  const optionId = (item: CommandItem) => `${uid}-opt-${item.id}`
  let listEl: HTMLElement | undefined = $state()

  function setActive(i: number) {
    const item = flat[i]
    if (!item) return
    internalActive = item.id
    if (value !== undefined) value = item.id
    onValueChange?.(item.id)
    listEl?.querySelector(`#${CSS.escape(optionId(item))}`)?.scrollIntoView({ block: 'nearest' })
  }

  function setSearch(next: string) {
    internalSearch = next
    if (search !== undefined) search = next
    onSearchChange?.(next)
  }

  function choose(item: CommandItem | undefined) {
    if (!item || item.disabled) return
    item.onSelect?.()
    onSelect?.(item)
    if (item.href) onNavigate(item.href)
  }

  function onKeydown(e: KeyboardEvent) {
    switch (e.key) {
      case 'ArrowDown':
        e.preventDefault()
        setActive(moveIndex(activeIndex, 'next', disabledList))
        break
      case 'ArrowUp':
        e.preventDefault()
        setActive(moveIndex(activeIndex, 'prev', disabledList))
        break
      case 'Home':
      case 'End':
        if (e.ctrlKey || e.metaKey) {
          e.preventDefault()
          setActive(moveIndex(activeIndex, e.key === 'Home' ? 'first' : 'last', disabledList))
        }
        break
      case 'Enter':
        if (e.isComposing) return
        e.preventDefault()
        choose(flat[activeIndex])
        break
    }
  }
</script>

<div {...rest} class="sky-command">
  <div class="sky-command__search">
    <Glyph name="search" size={14} />
    <input
      class="sky-command__input"
      type="text"
      role="combobox"
      aria-label={ariaLabel}
      aria-expanded="true"
      aria-controls={listId}
      aria-autocomplete="list"
      aria-activedescendant={flat[activeIndex] ? optionId(flat[activeIndex]) : undefined}
      autocomplete="off"
      autocapitalize="off"
      spellcheck="false"
      {placeholder}
      value={query}
      oninput={(e) => setSearch(e.currentTarget.value)}
      onkeydown={onKeydown}
    />
    {#if escHint}<kbd class="sky-command__kbd">esc</kbd>{/if}
  </div>
  <div class="sky-command__list" id={listId} role="listbox" aria-label={ariaLabel} aria-busy={loading || undefined} bind:this={listEl}>
    {#if loading && flat.length === 0}
      <div class="sky-command__empty" role="presentation">Searching…</div>
    {:else if flat.length === 0}
      <div class="sky-command__empty" role="presentation">{empty}</div>
    {/if}
    {#each shown as group (group.heading)}
      <div class="sky-command__group" role="group" aria-labelledby={`${uid}-g-${group.heading}`}>
        <div class="sky-command__heading" id={`${uid}-g-${group.heading}`} role="presentation">{group.heading}</div>
        {#each group.items as item (item.id)}
          {@const i = flat.indexOf(item)}
          {@const active = i === activeIndex}
          <!-- svelte-ignore a11y_click_events_have_key_events: keyboard selection goes through the combobox input (aria-activedescendant). -->
          <div
            class="sky-command__item"
            id={optionId(item)}
            role="option"
            tabindex="-1"
            aria-selected={active}
            aria-disabled={item.disabled || undefined}
            data-active={active || undefined}
            onpointermove={() => !item.disabled && i !== activeIndex && setActive(i)}
            onpointerdown={(e) => e.preventDefault()}
            onclick={() => choose(item)}
          >
            {#if item.icon}<span class="sky-command__icon">{@render item.icon()}</span>{/if}
            <span class="sky-command__label">{item.label}</span>
            {#if item.meta}<span class="sky-command__meta">{item.meta}</span>{/if}
            {#if item.shortcut}<kbd class="sky-command__kbd">{item.shortcut}</kbd>{:else if active}<kbd class="sky-command__kbd" aria-hidden="true">↵</kbd>{/if}
          </div>
        {/each}
      </div>
    {/each}
  </div>
</div>

<style>
  .sky-command {
    display: flex;
    flex-direction: column;
    min-width: 0;
    max-height: inherit;
    background: var(--ds-color-surface-raised);
    color: var(--ds-color-fg);
  }
  .sky-command__search {
    display: flex;
    align-items: center;
    gap: var(--ds-space-2-5);
    flex-shrink: 0;
    height: 3.25rem; /* 52 */
    padding: 0 var(--ds-space-4);
    border-bottom: var(--ds-border-width) solid var(--sky-color-border-muted);
    color: var(--ds-color-text-muted);
  }
  .sky-command__search:has(.sky-command__input:focus-visible) {
    box-shadow: inset 0 calc(var(--sky-focus-ring-width) * -1) 0 var(--sky-color-focus);
  }
  .sky-command__input {
    flex: 1 1 auto;
    min-width: 0;
    height: 100%;
    padding: 0;
    border: 0;
    background: transparent;
    color: var(--ds-color-fg);
    font: inherit;
    font-size: var(--sky-text-body);
  }
  .sky-command__input:focus-visible {
    outline: none;
  }
  .sky-command__input::placeholder {
    color: var(--ds-color-text-subtle);
    opacity: 1;
  }
  .sky-command__list {
    display: flex;
    flex-direction: column;
    gap: var(--ds-space-0-5);
    min-height: 0;
    max-height: min(26rem, 60dvh);
    padding: var(--ds-space-2);
    overflow-y: auto;
    overscroll-behavior: contain;
  }
  .sky-command__group {
    display: flex;
    flex-direction: column;
    gap: var(--ds-space-0-5);
  }
  .sky-command__heading {
    padding: var(--ds-space-2-5) var(--ds-space-3) var(--ds-space-1);
    font-family: var(--ds-font-mono);
    font-size: var(--sky-text-label);
    letter-spacing: var(--sky-tracking-label);
    text-transform: uppercase;
    color: var(--ds-color-text-subtle);
  }
  .sky-command__group:first-child .sky-command__heading {
    padding-top: var(--ds-space-2);
  }
  .sky-command__item {
    display: flex;
    align-items: center;
    gap: var(--ds-space-2-5);
    min-height: 2.375rem;
    padding: 0 var(--ds-space-3);
    border-radius: var(--ds-radius-md);
    font-size: 0.84375rem;
    cursor: pointer;
  }
  .sky-command__item[data-active] {
    background: var(--ds-color-overlay);
  }
  .sky-command__item[aria-disabled='true'] {
    opacity: 0.4;
    cursor: not-allowed;
  }
  /* Options never take focus (the input keeps it); this rule covers a stray programmatic focus. */
  .sky-command__item:focus-visible {
    outline: var(--sky-focus-ring-width) solid var(--sky-color-focus);
    outline-offset: calc(var(--sky-focus-ring-width) * -1);
  }
  .sky-command__icon {
    display: flex;
    color: var(--ds-color-text-muted);
  }
  .sky-command__label {
    flex: 1 1 auto;
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .sky-command__meta {
    display: none;
    flex-shrink: 1;
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    font-family: var(--ds-font-mono);
    font-size: 0.71875rem;
    color: var(--ds-color-text-subtle);
  }
  .sky-command__kbd {
    flex-shrink: 0;
    padding: 1px 6px;
    border: var(--ds-border-width) solid var(--sky-color-border-strong);
    border-radius: 5px;
    font-family: var(--ds-font-mono);
    font-size: var(--sky-text-label);
    color: var(--ds-color-text-muted);
  }
  .sky-command__empty {
    padding: var(--ds-space-6) var(--ds-space-3);
    text-align: center;
    font-size: var(--ds-text-sm);
    color: var(--ds-color-text-muted);
  }
  @media (pointer: coarse) {
    .sky-command__item {
      min-height: var(--sky-size-touch);
    }
    .sky-command__input {
      font-size: 1rem;
    }
  }
  @media (min-width: 30rem) {
    .sky-command__meta {
      display: block;
    }
  }
</style>
