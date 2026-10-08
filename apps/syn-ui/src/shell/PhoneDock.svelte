<!--
  Phone floating dock (PhoneDock board): Overview, Executions, Evals,
  Workflows and More. More opens a sheet with the remaining sections.
  Below 48rem only.
-->
<script lang="ts">
  import { href } from '../lib/router'
  import NavIcon from './NavIcon.svelte'
  import { DOCK, MORE, type NavKey } from './nav'

  let { active }: { active: NavKey | 'none' } = $props()

  let open = $state(false)
  let moreButton: HTMLButtonElement | undefined = $state()
  let sheet: HTMLElement | undefined = $state()
  const moreActive = $derived(MORE.some((m) => m.key === active))

  // Close on navigation.
  $effect(() => {
    void active
    open = false
  })

  // Focus the first item when the sheet opens; Escape and outside clicks close it.
  $effect(() => {
    if (!open) return
    sheet?.querySelector<HTMLElement>('a')?.focus()
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        open = false
        moreButton?.focus()
      }
    }
    const onPointer = (e: PointerEvent) => {
      const t = e.target as Node
      if (!sheet?.contains(t) && !moreButton?.contains(t)) open = false
    }
    document.addEventListener('keydown', onKey)
    document.addEventListener('pointerdown', onPointer)
    return () => {
      document.removeEventListener('keydown', onKey)
      document.removeEventListener('pointerdown', onPointer)
    }
  })
</script>

<div class="sky-dock-wrap">
  {#if open}
    <div class="sky-more" id="sky-more-sheet" bind:this={sheet} role="dialog" aria-label="More sections">
      <ul class="sky-more__list">
        {#each MORE as s (s.key)}
          <li>
            <a class="sky-more__item" href={href(s.href)} aria-current={active === s.key ? 'page' : undefined}>
              <span class="sky-more__icon"><NavIcon name={s.key} size={17} /></span>
              <span class="sky-more__label">{s.label}</span>
            </a>
          </li>
        {/each}
      </ul>
    </div>
  {/if}

  <nav class="sky-dock" aria-label="Primary">
    {#each DOCK as s (s.key)}
      <a class="sky-dock__item" href={href(s.href)} aria-current={active === s.key ? 'page' : undefined}>
        <span class="sky-dock__icon"><NavIcon name={s.key} size={18} /></span>
        <span>{s.label}</span>
      </a>
    {/each}
    <button
      class="sky-dock__item"
      type="button"
      bind:this={moreButton}
      aria-expanded={open}
      aria-controls="sky-more-sheet"
      data-current={moreActive || undefined}
      onclick={() => (open = !open)}
    >
      <span class="sky-dock__icon"><NavIcon name="more" size={18} /></span>
      <span>More</span>
    </button>
  </nav>
</div>

<style>
  .sky-dock-wrap {
    position: fixed;
    inset: auto 0 0 0;
    z-index: var(--sky-z-dock);
    padding: var(--ds-space-2) var(--sky-gutter) calc(var(--ds-space-4) + env(safe-area-inset-bottom));
    background: linear-gradient(to top, var(--ds-color-bg) 55%, transparent);
    pointer-events: none;
  }
  .sky-dock,
  .sky-more {
    pointer-events: auto;
  }

  .sky-dock {
    display: grid;
    grid-template-columns: repeat(5, minmax(0, 1fr));
    gap: var(--ds-space-0-5);
    padding: var(--ds-space-1-5);
    border-radius: var(--sky-radius-2xl);
    border: var(--ds-border-width) solid var(--sky-color-border-muted);
    background: var(--sky-color-control);
    box-shadow: var(--sky-shadow-dock);
    font-size: var(--sky-text-label);
    line-height: 1.2;
  }
  .sky-dock__item {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: var(--ds-space-1);
    min-width: 0;
    height: var(--sky-size-dock-item);
    padding: 0;
    border: 0;
    border-radius: var(--sky-radius-xl);
    background: transparent;
    color: var(--ds-color-text-muted);
    font: inherit;
    font-weight: var(--ds-font-weight-medium);
    text-decoration: none;
    cursor: pointer;
  }
  .sky-dock__item > span:last-child {
    max-width: 100%;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .sky-dock__icon {
    display: flex;
    color: var(--ds-color-text-subtle);
  }
  .sky-dock__item[aria-current='page'],
  .sky-dock__item[data-current],
  .sky-dock__item[aria-expanded='true'] {
    background: var(--ds-color-overlay);
    color: var(--ds-color-fg);
    font-weight: var(--ds-font-weight-semibold);
  }
  .sky-dock__item[aria-current='page'] .sky-dock__icon,
  .sky-dock__item[data-current] .sky-dock__icon,
  .sky-dock__item[aria-expanded='true'] .sky-dock__icon {
    color: var(--ds-color-accent);
  }

  .sky-more {
    margin: 0 0 var(--ds-space-2) auto;
    width: min(100%, 15rem);
    padding: var(--ds-space-1-5);
    border-radius: var(--sky-radius-xl);
    border: var(--ds-border-width) solid var(--sky-color-border-strong);
    background: var(--ds-color-surface-raised);
    box-shadow: var(--sky-shadow-overlay);
  }
  .sky-more__list {
    display: flex;
    flex-direction: column;
    gap: var(--ds-space-0-5);
    margin: 0;
    padding: 0;
    list-style: none;
  }
  .sky-more__item {
    display: flex;
    align-items: center;
    gap: var(--ds-space-2-5);
    min-height: var(--sky-size-touch);
    padding: 0 var(--ds-space-3);
    border-radius: var(--ds-radius-md);
    color: var(--ds-color-fg);
    font-size: var(--sky-text-body);
    text-decoration: none;
  }
  .sky-more__icon {
    display: flex;
    color: var(--ds-color-text-subtle);
  }
  .sky-more__item:hover,
  .sky-more__item[aria-current='page'] {
    background: var(--ds-color-overlay);
  }
  .sky-more__item[aria-current='page'] .sky-more__icon {
    color: var(--ds-color-accent);
  }

  .sky-dock__item:focus-visible,
  .sky-more__item:focus-visible {
    outline: var(--sky-focus-ring-width) solid var(--sky-color-focus);
    outline-offset: calc(var(--sky-focus-ring-offset) * -1);
  }

  @media (prefers-reduced-motion: no-preference) {
    .sky-more {
      animation: sky-more-in var(--sky-duration-base) var(--sky-ease-out);
    }
  }
  @keyframes sky-more-in {
    from {
      opacity: 0;
      transform: translateY(0.5rem);
    }
  }
</style>
