<!-- Phone top bar (PhoneTop board): wordmark, Live, 44px search and Run. Below 48rem only. -->
<script lang="ts">
  import type { LiveState } from '@syn137/skyline-core/patterns'
  import { href } from '../lib/router'
  import LiveBadge from './LiveBadge.svelte'
  import NavIcon from './NavIcon.svelte'
  import Wordmark from './Wordmark.svelte'

  let { live, onsearch }: { live: LiveState; onsearch: () => void } = $props()
</script>

<header class="sky-phonetop">
  <Wordmark href={href('/')} compact />
  <div class="sky-phonetop__actions">
    <span class="sky-phonetop__live"><LiveBadge state={live} size="sm" /></span>
    <button class="sky-phonetop__btn" type="button" aria-label="Search or jump to" onclick={onsearch}>
      <NavIcon name="search" size={17} />
    </button>
    <a class="sky-phonetop__btn sky-phonetop__run" href={href('/workflows')} aria-label="Run workflow">
      <NavIcon name="play" size={15} />
    </a>
  </div>
</header>

<style>
  .sky-phonetop {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: var(--ds-space-3);
    padding: var(--ds-space-3) var(--sky-gutter);
    font-size: var(--ds-text-sm);
    color: var(--ds-color-text-muted);
  }
  .sky-phonetop__actions {
    display: flex;
    align-items: center;
    gap: var(--ds-space-2);
    min-width: 0;
  }
  .sky-phonetop__btn {
    display: flex;
    align-items: center;
    justify-content: center;
    flex-shrink: 0;
    width: var(--sky-size-touch);
    height: var(--sky-size-touch);
    padding: 0;
    border-radius: var(--sky-radius-row);
    border: var(--ds-border-width) solid var(--ds-color-border);
    background: var(--sky-color-control);
    color: var(--ds-color-text-muted);
    cursor: pointer;
  }
  .sky-phonetop__run {
    border: 0;
    background: var(--sky-color-accent-solid);
    box-shadow: var(--sky-shadow-glow);
    color: var(--sky-color-accent-solid-contrast);
  }
  .sky-phonetop__btn:focus-visible {
    outline: var(--sky-focus-ring-width) solid var(--sky-color-focus);
    outline-offset: var(--sky-focus-ring-offset);
  }
  /* The Live pill joins from 360px; below that the bar holds wordmark and the two 44px buttons. */
  .sky-phonetop__live {
    display: none;
  }
  @media (min-width: 22.5rem) {
    .sky-phonetop__live {
      display: flex;
    }
  }
</style>
