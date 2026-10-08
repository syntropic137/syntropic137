<!-- Dropdown Menu (DropdownMenuRootContract): role=menu with roving focus and type-ahead. -->
<script lang="ts">
  import { tick, untrack } from 'svelte'
  import { moveIndex, typeaheadIndex } from '@syn137/skyline-core/state'
  import { hideFromTopLayer, popoverAttr, positionFloating, pushLayer, showInTopLayer } from '../_internal/layers'
  import { refAttachment, type TriggerProps } from '../_internal/trigger'
  import type { DropdownMenuProps, MenuItem } from './types'

  let {
    open = $bindable(),
    defaultOpen = false,
    onOpenChange,
    items,
    label,
    side = 'bottom',
    align = 'start',
    width = '13.75rem',
    onSelect,
    trigger,
  }: DropdownMenuProps = $props()

  const uid = $props.id()
  const menuId = `${uid}-menu`
  let internal = $state(untrack(() => defaultOpen))
  const isOpen = $derived(open ?? internal)
  let anchor: HTMLElement | null = $state(null)
  let surface: HTMLElement | undefined = $state()
  let refs: HTMLElement[] = $state([])
  let active = $state(-1)
  /** Where focus lands when the menu opens. */
  let openAt: 'first' | 'last' = 'first'
  let query = ''
  let queryTimer: ReturnType<typeof setTimeout> | undefined

  /** Item entries only, with their index into `items`. */
  const actionable = $derived(items.flatMap((e, i) => (e.type === 'separator' || e.type === 'label' ? [] : [{ item: e as MenuItem, index: i }])))
  const disabledList = $derived(actionable.map((a) => !!a.item.disabled))

  function set(next: boolean, opts: { returnFocus?: boolean } = {}) {
    if (next === isOpen) return
    internal = next
    if (open !== undefined) open = next
    onOpenChange?.(next)
    if (!next) {
      active = -1
      if (opts.returnFocus) anchor?.focus()
    }
  }

  function focusItem(i: number) {
    if (i < 0) return
    active = i
    refs[i]?.focus({ preventScroll: false })
  }

  $effect(() => {
    if (!isOpen || !anchor || !surface) return
    const el = surface
    const a = anchor
    showInTopLayer(el)
    const stopPosition = positionFloating(a, el, { side, align, offset: 6 })
    const popLayer = pushLayer({
      contains: (t) => el.contains(t) || a.contains(t),
      onEscape: () => set(false, { returnFocus: true }),
      onOutside: () => set(false),
    })
    void tick().then(() => {
      const current = actionable.findIndex((x) => x.item.current)
      focusItem(current >= 0 && openAt === 'first' ? current : moveIndex(-1, openAt, disabledList))
    })
    return () => {
      stopPosition()
      popLayer()
      hideFromTopLayer(el)
    }
  })

  function choose(i: number, e?: Event) {
    const entry = actionable[i]
    if (!entry || entry.item.disabled) {
      e?.preventDefault()
      return
    }
    entry.item.onSelect?.()
    onSelect?.(entry.item)
    // Links navigate; focus should follow the page, not the trigger.
    set(false, { returnFocus: !entry.item.href })
  }

  function onMenuKeydown(e: KeyboardEvent) {
    const i = active
    switch (e.key) {
      case 'ArrowDown':
        e.preventDefault()
        focusItem(moveIndex(i, 'next', disabledList))
        return
      case 'ArrowUp':
        e.preventDefault()
        focusItem(moveIndex(i, 'prev', disabledList))
        return
      case 'Home':
        e.preventDefault()
        focusItem(moveIndex(i, 'first', disabledList))
        return
      case 'End':
        e.preventDefault()
        focusItem(moveIndex(i, 'last', disabledList))
        return
      case 'Tab':
        set(false)
        return
      case ' ':
        if (!actionable[i]?.item.href) {
          e.preventDefault()
          choose(i)
        }
        return
    }
    if (e.key.length === 1 && !e.ctrlKey && !e.metaKey && !e.altKey) {
      clearTimeout(queryTimer)
      query += e.key
      queryTimer = setTimeout(() => (query = ''), 500)
      const hit = typeaheadIndex(
        actionable.map((a) => a.item.label),
        disabledList,
        i,
        query,
      )
      if (hit >= 0) focusItem(hit)
    }
  }

  function onTriggerKeydown(e: KeyboardEvent) {
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      e.preventDefault()
      openAt = e.key === 'ArrowUp' ? 'last' : 'first'
      if (isOpen) focusItem(moveIndex(-1, openAt, disabledList))
      else set(true)
    }
  }

  const ref = refAttachment((node) => (anchor = node))
  const triggerProps: TriggerProps = $derived({
    ...ref,
    'aria-haspopup': 'menu',
    'aria-expanded': isOpen,
    'aria-controls': isOpen ? menuId : undefined,
    'data-state': isOpen ? 'open' : 'closed',
    onclick: () => {
      openAt = 'first'
      set(!isOpen)
    },
    onkeydown: onTriggerKeydown,
  })

  /** Position in `actionable` for an entry index. */
  const positionOf = $derived(new Map(actionable.map((a, k) => [a.index, k])))
</script>

{@render trigger(triggerProps)}
{#if isOpen}
  <div
    bind:this={surface}
    class="sky-menu"
    id={menuId}
    role="menu"
    aria-label={label}
    aria-orientation="vertical"
    tabindex="-1"
    popover={popoverAttr}
    data-state="open"
    style:width
    onkeydown={onMenuKeydown}
  >
    {#each items as entry, i (i)}
      {#if entry.type === 'separator'}
        <div class="sky-menu__separator" role="separator"></div>
      {:else if entry.type === 'label'}
        <div class="sky-menu__label" role="presentation">{entry.label}</div>
      {:else}
        {@const k = positionOf.get(i) ?? -1}
        {@const item = entry as MenuItem}
        {#if item.href && !item.disabled}
          <a
            bind:this={refs[k]}
            class="sky-menu__item"
            role="menuitem"
            href={item.href}
            tabindex={k === active ? 0 : -1}
            aria-current={item.current ? 'page' : undefined}
            data-tone={item.tone}
            data-highlighted={k === active || undefined}
            onclick={() => choose(k)}
            onpointermove={() => focusItem(k)}
          >
            {#if item.icon}<span class="sky-menu__icon">{@render item.icon()}</span>{/if}
            <span class="sky-menu__text">{item.label}</span>
            {#if item.meta}<span class="sky-menu__meta">{item.meta}</span>{/if}
          </a>
        {:else}
          <button
            bind:this={refs[k]}
            type="button"
            class="sky-menu__item"
            role="menuitem"
            tabindex={k === active ? 0 : -1}
            aria-disabled={item.disabled || undefined}
            data-tone={item.tone}
            data-highlighted={k === active || undefined}
            onclick={(e) => choose(k, e)}
            onpointermove={() => !item.disabled && focusItem(k)}
          >
            {#if item.icon}<span class="sky-menu__icon">{@render item.icon()}</span>{/if}
            <span class="sky-menu__text">{item.label}</span>
            {#if item.meta}<span class="sky-menu__meta">{item.meta}</span>{/if}
          </button>
        {/if}
      {/if}
    {/each}
  </div>
{/if}

<style>
  .sky-menu {
    position: fixed;
    inset: auto;
    z-index: var(--sky-z-overlay);
    display: flex;
    flex-direction: column;
    gap: var(--ds-space-0-5);
    box-sizing: border-box;
    max-width: calc(100vw - 2 * var(--ds-space-2));
    max-height: max(12rem, var(--sky-available));
    margin: 0;
    padding: var(--ds-space-1-5);
    border: var(--ds-border-width) solid var(--sky-color-border-strong);
    border-radius: var(--sky-radius-xl);
    background: var(--ds-color-surface-raised);
    box-shadow: var(--sky-shadow-overlay);
    color: var(--ds-color-fg);
    overflow: auto;
    overscroll-behavior: contain;
  }
  .sky-menu:focus-visible {
    outline: none;
  }
  .sky-menu__item {
    display: flex;
    align-items: center;
    gap: var(--ds-space-2-5);
    flex-shrink: 0;
    box-sizing: border-box;
    width: 100%;
    min-height: 2.375rem; /* 38 */
    padding: 0 var(--ds-space-3);
    border: 0;
    border-radius: var(--ds-radius-md);
    background: transparent;
    color: inherit;
    font-family: inherit;
    font-size: 0.84375rem;
    text-align: left;
    text-decoration: none;
    cursor: pointer;
    -webkit-tap-highlight-color: transparent;
  }
  .sky-menu__item[data-highlighted],
  .sky-menu__item[aria-current='page'] {
    background: var(--ds-color-overlay);
  }
  .sky-menu__item[aria-disabled='true'] {
    opacity: 0.4;
    cursor: not-allowed;
  }
  .sky-menu__item[data-tone='danger'] {
    color: var(--sky-color-danger-soft-fg);
  }
  .sky-menu__item:focus-visible {
    outline: var(--sky-focus-ring-width) solid var(--sky-color-focus);
    outline-offset: calc(var(--sky-focus-ring-width) * -1);
  }
  .sky-menu__icon {
    display: flex;
    color: var(--ds-color-text-muted);
  }
  .sky-menu__text {
    flex: 1 1 auto;
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .sky-menu__meta {
    font-family: var(--ds-font-mono);
    font-size: 0.71875rem;
    color: var(--ds-color-text-subtle);
  }
  .sky-menu__separator {
    height: var(--ds-border-width);
    margin: var(--ds-space-1) var(--ds-space-2);
    background: var(--sky-color-border-muted);
  }
  .sky-menu__label {
    padding: var(--ds-space-2) var(--ds-space-3) var(--ds-space-1);
    font-family: var(--ds-font-mono);
    font-size: var(--sky-text-label);
    letter-spacing: var(--sky-tracking-label);
    text-transform: uppercase;
    color: var(--ds-color-text-subtle);
  }
  @media (pointer: coarse) {
    .sky-menu__item {
      min-height: var(--sky-size-touch);
      font-size: var(--ds-text-md);
    }
  }
  @media (prefers-reduced-motion: no-preference) {
    .sky-menu {
      animation: sky-menu-in var(--sky-duration-base) var(--sky-ease-out);
    }
  }
  @keyframes sky-menu-in {
    from {
      opacity: 0;
      transform: translateY(-4px);
    }
  }
</style>
