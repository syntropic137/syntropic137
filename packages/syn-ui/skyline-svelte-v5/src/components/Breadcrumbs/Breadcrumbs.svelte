<!--
  Breadcrumbs (CompNav "Breadcrumbs"): desktop trail with the current page as
  a pill; "phone, collapsed" shows Home, "…", the parent and the current page.
-->
<script lang="ts">
  import Glyph from '../_internal/Glyph.svelte'
  import type { BreadcrumbsProps } from './types'

  let { items, homeHref, homeLabel = 'Overview', collapse = 'auto', 'aria-label': ariaLabel = 'Breadcrumb', ...rest }: BreadcrumbsProps = $props()

  let expanded = $state(false)
  $effect(() => {
    void items
    expanded = false
  })
  const middleCount = $derived(collapse === 'auto' ? Math.max(0, items.length - 2) : 0)
</script>

{#if items.length > 0 || homeHref}
  <nav {...rest} class="sky-breadcrumbs" aria-label={ariaLabel} data-expanded={expanded || undefined}>
    <ol class="sky-breadcrumbs__list">
      {#if homeHref}
        <li class="sky-breadcrumbs__step">
          <a class="sky-breadcrumbs__home" href={homeHref} aria-label={homeLabel}><Glyph name="home" size={16} /></a>
        </li>
      {/if}
      {#if middleCount > 0}
        <li class="sky-breadcrumbs__step sky-breadcrumbs__ellipsis">
          {#if homeHref}<span class="sky-breadcrumbs__sep"><Glyph name="chevron-right" size={12} strokeWidth={1.75} /></span>{/if}
          <button class="sky-breadcrumbs__more" type="button" aria-label="Show the full path" aria-expanded={expanded} onclick={() => (expanded = true)}>…</button>
        </li>
      {/if}
      {#each items as c, i (i)}
        {@const current = i === items.length - 1}
        <li class="sky-breadcrumbs__step" data-middle={i < middleCount || undefined}>
          {#if homeHref || i > 0}<span class="sky-breadcrumbs__sep"><Glyph name="chevron-right" size={12} strokeWidth={1.75} /></span>{/if}
          {#if current || !c.href}
            <span class="sky-breadcrumbs__current" data-pill={current || undefined} aria-current={current ? 'page' : undefined}>
              {c.label}{#if c.id}&nbsp;<span class="sky-breadcrumbs__id">{c.id}</span>{/if}
            </span>
          {:else}
            <a class="sky-breadcrumbs__link" href={c.href}>
              {c.label}{#if c.id}&nbsp;<span class="sky-breadcrumbs__id">{c.id}</span>{/if}
            </a>
          {/if}
        </li>
      {/each}
    </ol>
  </nav>
{/if}

<style>
  .sky-breadcrumbs {
    min-width: 0;
    min-height: var(--sky-size-touch);
    font-size: var(--ds-text-md);
  }
  .sky-breadcrumbs__list {
    display: flex;
    align-items: center;
    gap: var(--ds-space-0-5);
    min-width: 0;
    margin: 0;
    padding: 0;
    list-style: none;
  }
  .sky-breadcrumbs[data-expanded] .sky-breadcrumbs__list {
    flex-wrap: wrap;
  }
  .sky-breadcrumbs__step {
    display: flex;
    align-items: center;
    gap: var(--ds-space-0-5);
    min-width: 0;
  }
  .sky-breadcrumbs__step[data-middle] {
    display: none;
  }
  .sky-breadcrumbs[data-expanded] .sky-breadcrumbs__step[data-middle] {
    display: flex;
  }
  .sky-breadcrumbs[data-expanded] .sky-breadcrumbs__ellipsis {
    display: none;
  }
  .sky-breadcrumbs__sep {
    display: flex;
    flex-shrink: 0;
    color: var(--ds-color-text-subtle);
    opacity: 0.7;
  }
  .sky-breadcrumbs__home,
  .sky-breadcrumbs__more {
    display: flex;
    align-items: center;
    justify-content: center;
    flex-shrink: 0;
    width: 2.5rem;
    height: var(--sky-size-touch);
    padding: 0;
    border: 0;
    border-radius: var(--ds-radius-md);
    background: transparent;
    color: var(--ds-color-text-muted);
    font: inherit;
    font-size: var(--ds-text-lg);
    cursor: pointer;
  }
  .sky-breadcrumbs__link,
  .sky-breadcrumbs__current {
    min-width: 3rem;
    padding: 0 var(--ds-space-1-5);
    line-height: var(--sky-size-touch);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .sky-breadcrumbs__link {
    color: var(--ds-color-text-muted);
    text-decoration: none;
    border-radius: var(--ds-radius-md);
  }
  .sky-breadcrumbs__link:hover,
  .sky-breadcrumbs__home:hover,
  .sky-breadcrumbs__more:hover {
    color: var(--ds-color-fg);
  }
  .sky-breadcrumbs__current {
    color: var(--ds-color-text-muted);
  }
  .sky-breadcrumbs__current[data-pill] {
    font-weight: var(--ds-font-weight-semibold);
    color: var(--ds-color-fg);
  }
  .sky-breadcrumbs__id {
    font-family: var(--ds-font-mono);
    font-size: var(--sky-text-data);
  }
  .sky-breadcrumbs__home:focus-visible,
  .sky-breadcrumbs__more:focus-visible,
  .sky-breadcrumbs__link:focus-visible {
    outline: var(--sky-focus-ring-width) solid var(--sky-color-focus);
    outline-offset: calc(var(--sky-focus-ring-offset) * -1);
  }

  @media (min-width: 48rem) {
    .sky-breadcrumbs {
      min-height: 0;
      font-size: var(--ds-text-sm);
    }
    .sky-breadcrumbs__list {
      flex-wrap: wrap;
      gap: var(--ds-space-1);
    }
    .sky-breadcrumbs__step[data-middle] {
      display: flex;
    }
    .sky-breadcrumbs__ellipsis {
      display: none;
    }
    .sky-breadcrumbs__home {
      width: 1.875rem;
      height: 1.875rem;
    }
    .sky-breadcrumbs__link,
    .sky-breadcrumbs__current {
      min-width: 0;
      padding: 0 var(--ds-space-2);
      line-height: 1.75rem;
    }
    .sky-breadcrumbs__current[data-pill] {
      display: flex;
      align-items: center;
      height: 1.75rem;
      padding: 0 var(--ds-space-2-5);
      border-radius: var(--ds-radius-sm);
      border: var(--ds-border-width) solid var(--ds-color-border);
      background: var(--sky-color-control);
      box-shadow: var(--sky-shadow-raised);
    }
    .sky-breadcrumbs__id {
      font-size: var(--ds-text-xs);
    }
  }
  @media (min-width: 48rem) and (pointer: coarse) {
    .sky-breadcrumbs__home,
    .sky-breadcrumbs__link {
      min-height: var(--sky-size-touch);
      line-height: var(--sky-size-touch);
    }
  }
</style>
