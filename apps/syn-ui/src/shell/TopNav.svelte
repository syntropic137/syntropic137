<!--
  Desktop and tablet top bar (TopNav board): wordmark, the capsule with all
  eight sections, then Live, search and Run workflow. From 48rem only; the
  phone gets PhoneTop + PhoneDock instead.

  One row from 64rem, never wrapping: the capsule shows icons only (labels
  stay for screen readers and as tooltips) until 90rem, where the labels
  fit beside the actions (at 80rem they do not, by about 90px). Feedback
  is the floating bubble, not a top-bar button.
-->
<script lang="ts">
  import type { LiveState } from '@syn137/skyline-core/patterns'
  import { href } from '../lib/router'
  import LiveBadge from './LiveBadge.svelte'
  import NavIcon from './NavIcon.svelte'
  import Wordmark from './Wordmark.svelte'
  import { SECTIONS, type NavKey } from './nav'

  let { active, live, onsearch }: { active: NavKey | 'none'; live: LiveState; onsearch: () => void } = $props()
</script>

<header class="sky-topnav">
  <Wordmark href={href('/')} />

  <nav class="sky-capsule" aria-label="Primary">
    {#each SECTIONS as s (s.key)}
      <a class="sky-capsule__item" href={href(s.href)} title={s.label} aria-current={active === s.key ? 'page' : undefined}>
        <span class="sky-capsule__icon"><NavIcon name={s.key} /></span>
        <span class="sky-capsule__label">{s.label}</span>
      </a>
    {/each}
  </nav>

  <div class="sky-topnav__actions">
    <LiveBadge state={live} />
    <button class="sky-topnav__search" type="button" aria-label="Search or jump to" aria-keyshortcuts="Meta+K Control+K" onclick={onsearch}>
      <NavIcon name="search" size={14} />
      <kbd class="sky-topnav__kbd">⌘K</kbd>
    </button>
    <a class="sky-topnav__run" href={href('/workflows')}>
      <NavIcon name="play" size={13} />
      <span>Run workflow</span>
    </a>
  </div>
</header>

<style>
  .sky-topnav {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    justify-content: space-between;
    gap: var(--ds-space-3-5) var(--ds-space-5);
    box-sizing: border-box;
    width: 100%;
    max-width: var(--sky-page-max);
    margin: 0 auto;
    padding: var(--ds-space-5) var(--sky-gutter);
    font-size: var(--ds-text-sm);
    line-height: var(--ds-line-height-snug);
    color: var(--ds-color-text-muted);
  }

  .sky-capsule {
    display: flex;
    flex-wrap: wrap;
    gap: var(--ds-space-0-5);
    padding: var(--ds-space-1);
    border-radius: var(--sky-radius-row);
    border: var(--ds-border-width) solid var(--ds-color-border);
    background: var(--sky-color-control);
    box-shadow: var(--sky-shadow-float);
  }
  .sky-capsule__item {
    display: flex;
    align-items: center;
    gap: var(--ds-space-2);
    height: var(--sky-size-nav-item);
    padding: 0 var(--ds-space-3);
    border-radius: var(--ds-radius-md);
    text-decoration: none;
    color: var(--ds-color-text-muted);
    font-weight: var(--ds-font-weight-medium);
    transition: background-color var(--sky-duration-fast) var(--sky-ease-out), color var(--sky-duration-fast) var(--sky-ease-out);
  }
  .sky-capsule__icon {
    display: flex;
    color: var(--ds-color-text-subtle);
  }
  .sky-capsule__item:hover {
    color: var(--ds-color-fg);
    background: var(--sky-color-control-hover);
  }
  .sky-capsule__item[aria-current='page'] {
    background: var(--ds-color-overlay);
    color: var(--ds-color-fg);
    font-weight: var(--ds-font-weight-semibold);
    box-shadow: var(--sky-shadow-selected);
  }
  .sky-capsule__item[aria-current='page'] .sky-capsule__icon {
    color: var(--ds-color-accent);
  }

  .sky-topnav__actions {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: var(--ds-space-2-5);
  }
  .sky-topnav__search {
    display: flex;
    align-items: center;
    gap: var(--ds-space-2);
    height: var(--sky-size-nav-item);
    padding: 0 var(--ds-space-2-5);
    border-radius: var(--ds-radius-md);
    border: var(--ds-border-width) solid var(--ds-color-border);
    background: var(--sky-color-control);
    color: var(--ds-color-text-muted);
    font: inherit;
    cursor: pointer;
  }
  .sky-topnav__search:hover {
    border-color: var(--sky-color-border-hover);
    color: var(--ds-color-fg);
  }
  .sky-topnav__kbd {
    font-family: var(--ds-font-mono);
    font-size: var(--sky-text-label);
    padding: 1px 5px;
    border-radius: var(--ds-radius-xs);
    border: var(--ds-border-width) solid var(--sky-color-border-strong);
  }
  .sky-topnav__run {
    display: flex;
    align-items: center;
    gap: var(--ds-space-2);
    height: var(--sky-size-nav-item);
    padding: 0 var(--ds-space-3-5);
    border-radius: var(--ds-radius-md);
    background: var(--sky-color-accent-solid);
    box-shadow: var(--sky-shadow-glow);
    color: var(--sky-color-accent-solid-contrast);
    font-weight: var(--ds-font-weight-semibold);
    text-decoration: none;
    white-space: nowrap;
  }
  .sky-topnav__run:hover {
    background: var(--ds-color-accent);
  }

  .sky-capsule__item:focus-visible,
  .sky-topnav__search:focus-visible,
  .sky-topnav__run:focus-visible {
    outline: var(--sky-focus-ring-width) solid var(--sky-color-focus);
    outline-offset: var(--sky-focus-ring-offset);
  }

  /* Desktop: one row, no wrapping (owner tweak, Oct 8 2026). */
  @media (min-width: 64rem) {
    .sky-topnav,
    .sky-capsule,
    .sky-topnav__actions {
      flex-wrap: nowrap;
    }
    .sky-topnav {
      gap: var(--ds-space-4);
    }
    .sky-topnav__actions {
      gap: var(--ds-space-2);
      flex-shrink: 0;
    }
    .sky-capsule__item {
      padding: 0 var(--ds-space-2-5);
    }
    .sky-capsule__label {
      position: absolute;
      width: 1px;
      height: 1px;
      overflow: hidden;
      clip-path: inset(50%);
      white-space: nowrap;
    }
  }
  @media (min-width: 90rem) {
    .sky-capsule__label {
      position: static;
      width: auto;
      height: auto;
      overflow: visible;
      clip-path: none;
    }
  }

  @media (pointer: coarse) {
    .sky-capsule__item,
    .sky-topnav__search,
    .sky-topnav__run {
      min-height: var(--sky-size-touch);
    }
  }
</style>
