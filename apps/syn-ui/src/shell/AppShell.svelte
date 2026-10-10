<!--
  App Shell: top capsule nav from 48rem, phone top bar + floating dock
  below it, the breadcrumb row, and the page column (max 1400px).
  Both nav forms are in the DOM; CSS shows one, so there is no layout jump
  and no JS media query.
-->
<script lang="ts">
  import type { Snippet } from 'svelte'
  import type { Crumb, LiveState } from '@syn137/skyline-core/patterns'
  import BreadcrumbTrail from './BreadcrumbTrail.svelte'
  import { FEEDBACK_LOCAL_ONLY, feedbackUi } from './feedback.svelte'
  import { overlays } from './overlays.svelte'
  import PhoneDock from './PhoneDock.svelte'
  import PhoneTop from './PhoneTop.svelte'
  import TopNav from './TopNav.svelte'
  import type { NavKey } from './nav'

  let {
    active,
    crumbs,
    live,
    onsearch,
    children,
  }: { active: NavKey | 'none'; crumbs: Crumb[]; live: LiveState; onsearch: () => void; children: Snippet } = $props()
</script>

<a class="sky-skip" href="#sky-main">Skip to content</a>

<div class="sky-shell">
  <div class="sky-shell__desktop-nav"><TopNav {active} {live} {onsearch} /></div>
  <div class="sky-shell__phone-nav"><PhoneTop {live} {onsearch} /></div>

  {#if crumbs.length > 0}
    <div class="sky-shell__crumbs"><BreadcrumbTrail {crumbs} /></div>
  {/if}

  <main class="sky-shell__main" id="sky-main" tabindex="-1">
    {@render children()}
  </main>

  <div class="sky-shell__phone-nav"><PhoneDock {active} {onsearch} /></div>
</div>

{#if FEEDBACK_LOCAL_ONLY}
  <!-- Lazy, developer machines only: the bubble and its dialog never join a production build's first load. -->
  {#await import('./FeedbackBubble.svelte') then { default: FeedbackBubble }}<FeedbackBubble />{/await}
  {#if feedbackUi.mounted}
    {#await import('./FeedbackDialog.svelte') then { default: FeedbackDialog }}<FeedbackDialog />{/await}
  {/if}
{/if}

{#if overlays.paletteMounted || overlays.shortcutsMounted}
  <!-- Lazy: the palette and shortcuts overlay load on first open, never in the first load. -->
  {#await import('./ShellOverlays.svelte') then { default: ShellOverlays }}<ShellOverlays />{/await}
{/if}

<style>
  .sky-shell {
    display: flex;
    flex-direction: column;
    min-height: 100dvh;
  }
  .sky-shell__desktop-nav {
    display: none;
  }
  .sky-shell__crumbs {
    box-sizing: border-box;
    width: 100%;
    max-width: var(--sky-page-max);
    margin: 0 auto;
    padding: 0 var(--sky-gutter);
  }
  .sky-shell__main {
    display: flex;
    flex-direction: column;
    gap: var(--ds-space-4);
    flex-grow: 1;
    box-sizing: border-box;
    width: 100%;
    max-width: var(--sky-page-max);
    margin: 0 auto;
    padding: 0 var(--sky-gutter) calc(var(--sky-dock-clearance) + env(safe-area-inset-bottom));
    outline: none;
  }

  .sky-skip {
    position: absolute;
    left: var(--ds-space-2);
    top: calc(var(--ds-space-12) * -1);
    z-index: var(--sky-z-toast);
    padding: var(--ds-space-2) var(--ds-space-3);
    border-radius: var(--ds-radius-md);
    background: var(--sky-color-accent-solid);
    color: var(--sky-color-accent-solid-contrast);
  }
  .sky-skip:focus-visible {
    top: var(--ds-space-2);
    outline: var(--sky-focus-ring-width) solid var(--sky-color-focus);
    outline-offset: var(--sky-focus-ring-offset);
  }

  @media (min-width: 48rem) {
    .sky-shell__desktop-nav {
      display: block;
    }
    .sky-shell__phone-nav {
      display: none;
    }
    .sky-shell__crumbs {
      padding-bottom: var(--ds-space-3-5);
    }
    .sky-shell__main {
      gap: var(--ds-space-6);
      padding-top: var(--ds-space-2);
      padding-bottom: var(--ds-space-16);
    }
  }
</style>
