<!--
  Navigation Menu (NavigationMenuRootContract): the capsule (TopNav board)
  and the dock with More (PhoneDock board). Which one shows at which width
  is the App Shell's job; this component draws either.
-->
<script lang="ts">
  import Glyph from '../_internal/Glyph.svelte'
  import DropdownMenu from '../DropdownMenu/DropdownMenu.svelte'
  import type { MenuItem } from '../DropdownMenu/types'
  import type { NavigationMenuItem, NavigationMenuProps } from './types'

  let {
    items,
    variant = 'capsule',
    value,
    defaultValue,
    onValueChange,
    orientation = 'horizontal',
    more = [],
    moreLabel = 'More',
    moreIcon,
    'aria-label': ariaLabel = 'Primary',
    ...rest
  }: NavigationMenuProps = $props()

  const currentValue = $derived(value ?? [...items, ...more].find((i) => i.current)?.value ?? defaultValue)
  const isCurrent = (item: NavigationMenuItem) => item.value === currentValue
  const moreCurrent = $derived(more.some(isCurrent))
  const moreItems: MenuItem[] = $derived(
    more.map((m) => ({ label: m.label, value: m.value, href: m.href, meta: m.meta, current: isCurrent(m), icon: m.icon })),
  )
</script>

<nav {...rest} class="sky-nav" data-variant={variant} data-orientation={orientation} aria-label={ariaLabel}>
  <ul class="sky-nav__list" data-count={items.length + (variant === 'dock' && more.length ? 1 : 0)}>
    {#each items as item (item.value)}
      <li class="sky-nav__cell">
        <a class="sky-nav__item" href={item.href} aria-current={isCurrent(item) ? 'page' : undefined} onclick={() => onValueChange?.(item.value)}>
          {#if item.icon}<span class="sky-nav__icon">{@render item.icon()}</span>{/if}
          <span class="sky-nav__label">{item.label}</span>
        </a>
      </li>
    {/each}
    {#if variant === 'dock' && more.length}
      <li class="sky-nav__cell">
        <DropdownMenu items={moreItems} label={moreLabel} side="top" align="end" onSelect={(m) => onValueChange?.(m.value ?? m.label)}>
          {#snippet trigger(props)}
            <button {...props} type="button" class="sky-nav__item" data-current={moreCurrent || undefined}>
              <span class="sky-nav__icon">{#if moreIcon}{@render moreIcon()}{:else}<Glyph name="more" size={18} />{/if}</span>
              <span class="sky-nav__label">{moreLabel}</span>
            </button>
          {/snippet}
        </DropdownMenu>
      </li>
    {/if}
  </ul>
</nav>

<style>
  .sky-nav__list {
    margin: 0;
    padding: 0;
    list-style: none;
  }
  .sky-nav__cell {
    display: flex;
    min-width: 0;
  }
  .sky-nav__item {
    display: flex;
    align-items: center;
    min-width: 0;
    border: 0;
    background: transparent;
    color: var(--ds-color-text-muted);
    font-family: inherit;
    font-weight: var(--ds-font-weight-medium);
    text-decoration: none;
    cursor: pointer;
    -webkit-tap-highlight-color: transparent;
    transition:
      background-color var(--sky-duration-fast) var(--sky-ease-out),
      color var(--sky-duration-fast) var(--sky-ease-out);
  }
  .sky-nav__icon {
    display: flex;
    color: var(--ds-color-text-subtle);
  }
  .sky-nav__label {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .sky-nav__item:hover {
    color: var(--ds-color-fg);
  }
  .sky-nav__item[aria-current='page'],
  .sky-nav__item[data-current] {
    color: var(--ds-color-fg);
    font-weight: var(--ds-font-weight-semibold);
  }
  .sky-nav__item[aria-current='page'] .sky-nav__icon,
  .sky-nav__item[data-current] .sky-nav__icon {
    color: var(--ds-color-accent);
  }
  .sky-nav__item:focus-visible {
    outline: var(--sky-focus-ring-width) solid var(--sky-color-focus);
    outline-offset: var(--sky-focus-ring-offset);
  }

  /* ---- Capsule (TopNav) ---- */
  .sky-nav[data-variant='capsule'] {
    display: inline-flex;
    max-width: 100%;
  }
  .sky-nav[data-variant='capsule'] .sky-nav__list {
    display: flex;
    flex-wrap: wrap;
    gap: var(--ds-space-0-5);
    padding: var(--ds-space-1);
    border: var(--ds-border-width) solid var(--ds-color-border);
    border-radius: var(--sky-radius-row);
    background: var(--sky-color-control);
    box-shadow: var(--sky-shadow-float);
  }
  .sky-nav[data-variant='capsule'][data-orientation='vertical'] .sky-nav__list {
    flex-direction: column;
  }
  .sky-nav[data-variant='capsule'] .sky-nav__item {
    gap: var(--ds-space-2);
    width: 100%;
    height: var(--sky-size-nav-item);
    padding: 0 var(--ds-space-3);
    border-radius: var(--ds-radius-md);
    font-size: var(--ds-text-sm);
  }
  .sky-nav[data-variant='capsule'] .sky-nav__item:hover {
    background: var(--sky-color-control-hover);
  }
  .sky-nav[data-variant='capsule'] .sky-nav__item[aria-current='page'] {
    background: var(--ds-color-overlay);
    box-shadow: var(--sky-shadow-selected);
  }

  /* ---- Dock (PhoneDock) ---- */
  .sky-nav[data-variant='dock'] .sky-nav__list {
    display: grid;
    grid-auto-columns: minmax(0, 1fr);
    grid-auto-flow: column;
    gap: var(--ds-space-0-5);
    padding: var(--ds-space-1-5);
    border: var(--ds-border-width) solid var(--sky-color-border-muted);
    border-radius: var(--sky-radius-2xl);
    background: var(--sky-color-control);
    box-shadow: var(--sky-shadow-dock);
  }
  .sky-nav[data-variant='dock'] .sky-nav__cell > :global(*) {
    flex: 1 1 auto;
  }
  .sky-nav[data-variant='dock'] .sky-nav__item {
    flex: 1 1 auto;
    flex-direction: column;
    justify-content: center;
    gap: var(--ds-space-1);
    height: var(--sky-size-dock-item);
    padding: 0;
    border-radius: var(--sky-radius-xl);
    font-size: var(--sky-text-label);
    line-height: 1.2;
  }
  .sky-nav[data-variant='dock'] .sky-nav__label {
    max-width: 100%;
  }
  .sky-nav[data-variant='dock'] .sky-nav__item[aria-current='page'],
  .sky-nav[data-variant='dock'] .sky-nav__item[data-current],
  .sky-nav[data-variant='dock'] .sky-nav__item[aria-expanded='true'] {
    background: var(--ds-color-overlay);
    box-shadow: var(--sky-shadow-selected);
  }

  @media (pointer: coarse) {
    .sky-nav[data-variant='capsule'] .sky-nav__item {
      min-height: var(--sky-size-touch);
    }
  }
</style>
