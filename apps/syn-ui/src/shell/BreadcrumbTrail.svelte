<!--
  Breadcrumb Trail (CompNav board): Home, each parent, then the current page
  as a pill. On a phone the middle collapses behind an ellipsis button, and
  only the parent and the current page show. Not rendered on Overview.
-->
<script lang="ts">
  import type { Crumb } from '@syn137/skyline-core/patterns'
  import { href } from '../lib/router'
  import NavIcon from './NavIcon.svelte'

  let { crumbs }: { crumbs: Crumb[] } = $props()

  let expanded = $state(false)
  // Collapse again whenever the trail changes (new page).
  $effect(() => {
    void crumbs
    expanded = false
  })
  /** Crumbs before the parent; hidden behind "…" on phones. */
  const middleCount = $derived(Math.max(0, crumbs.length - 2))
</script>

{#if crumbs.length > 0}
  <nav class="sky-trail" aria-label="Breadcrumb" data-expanded={expanded || undefined}>
    <ol class="sky-trail__list">
      <li class="sky-trail__step">
        <a class="sky-trail__home" href={href('/')} aria-label="Overview"><NavIcon name="home" size={16} /></a>
      </li>
      {#if middleCount > 0}
        <li class="sky-trail__step sky-trail__ellipsis" aria-hidden={expanded}>
          <span class="sky-trail__sep"><NavIcon name="chevron" size={12} /></span>
          <button class="sky-trail__more" type="button" aria-label="Show the full path" onclick={() => (expanded = true)}>…</button>
        </li>
      {/if}
      {#each crumbs as c, i (i)}
        {@const current = i === crumbs.length - 1}
        <li class="sky-trail__step" data-middle={i < middleCount || undefined}>
          <span class="sky-trail__sep"><NavIcon name="chevron" size={12} /></span>
          {#if current || !c.href}
            <span class="sky-trail__current" aria-current={current ? 'page' : undefined}>
              {c.label}{#if c.id}&nbsp;<span class="sky-trail__id">{c.id}</span>{/if}
            </span>
          {:else}
            <a class="sky-trail__link" href={href(c.href)}>
              {c.label}{#if c.id}&nbsp;<span class="sky-trail__id">{c.id}</span>{/if}
            </a>
          {/if}
        </li>
      {/each}
    </ol>
  </nav>
{/if}

<style>
  .sky-trail {
    min-height: var(--sky-size-touch);
    margin: 0 calc(var(--ds-space-2) * -1);
    font-size: var(--ds-text-md);
  }
  .sky-trail__list {
    display: flex;
    align-items: center;
    gap: var(--ds-space-0-5);
    min-width: 0;
    margin: 0;
    padding: 0;
    list-style: none;
  }
  .sky-trail[data-expanded] .sky-trail__list {
    flex-wrap: wrap;
  }
  .sky-trail__step {
    display: flex;
    align-items: center;
    gap: var(--ds-space-0-5);
    min-width: 0;
  }
  .sky-trail__step[data-middle] {
    display: none;
  }
  .sky-trail[data-expanded] .sky-trail__step[data-middle] {
    display: flex;
  }
  .sky-trail[data-expanded] .sky-trail__ellipsis {
    display: none;
  }
  .sky-trail__sep {
    display: flex;
    flex-shrink: 0;
    color: var(--ds-color-text-subtle);
    opacity: 0.7;
  }
  .sky-trail__home,
  .sky-trail__more {
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
    letter-spacing: 0.08em;
    cursor: pointer;
  }
  .sky-trail__link,
  .sky-trail__current {
    min-width: 3rem;
    padding: 0 var(--ds-space-1-5);
    line-height: var(--sky-size-touch);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .sky-trail__link {
    color: var(--ds-color-text-muted);
    text-decoration: none;
    border-radius: var(--ds-radius-md);
  }
  .sky-trail__link:hover,
  .sky-trail__home:hover {
    color: var(--ds-color-fg);
  }
  .sky-trail__current {
    font-weight: var(--ds-font-weight-semibold);
    color: var(--ds-color-fg);
  }
  .sky-trail__id {
    font-family: var(--ds-font-mono);
    font-size: var(--sky-text-data);
  }
  .sky-trail__home:focus-visible,
  .sky-trail__more:focus-visible,
  .sky-trail__link:focus-visible {
    outline: var(--sky-focus-ring-width) solid var(--sky-color-focus);
    outline-offset: calc(var(--sky-focus-ring-offset) * -1);
  }

  @media (min-width: 48rem) {
    .sky-trail {
      min-height: 0;
      margin: 0;
      font-size: var(--ds-text-sm);
    }
    .sky-trail__list {
      flex-wrap: wrap;
      gap: var(--ds-space-1);
    }
    .sky-trail__step[data-middle] {
      display: flex;
    }
    .sky-trail__ellipsis {
      display: none;
    }
    .sky-trail__home {
      width: 1.875rem;
      height: 1.875rem;
    }
    .sky-trail__link,
    .sky-trail__current {
      min-width: 0;
      line-height: 1.75rem;
    }
    .sky-trail__current {
      display: flex;
      align-items: center;
      gap: var(--ds-space-1-5);
      height: 1.75rem;
      padding: 0 var(--ds-space-2-5);
      border-radius: var(--ds-radius-sm);
      border: var(--ds-border-width) solid var(--ds-color-border);
      background: var(--sky-color-control);
      box-shadow: var(--sky-shadow-raised);
    }
    .sky-trail__id {
      font-size: var(--ds-text-xs);
    }
  }
  @media (min-width: 48rem) and (pointer: coarse) {
    .sky-trail__home,
    .sky-trail__link {
      min-height: var(--sky-size-touch);
      line-height: var(--sky-size-touch);
    }
  }
</style>
