<!-- Live connection pill: blue dot with a halo when live, muted otherwise. -->
<script lang="ts">
  import type { LiveState } from '@syn137/skyline-core/patterns'

  let { state, size = 'md' }: { state: LiveState; size?: 'sm' | 'md' } = $props()
  const LABEL: Record<LiveState, string> = { live: 'Live', connecting: 'Connecting', offline: 'Offline', fixtures: 'Fixtures' }
</script>

<span class="sky-live" data-state={state} data-size={size} role="status" aria-live="polite">
  <span class="sky-live__dot" aria-hidden="true"></span>
  <span>{LABEL[state]}</span>
</span>

<style>
  .sky-live {
    display: inline-flex;
    align-items: center;
    gap: var(--ds-space-2);
    height: var(--sky-size-nav-item);
    padding: 0 var(--ds-space-3);
    border-radius: var(--ds-radius-md);
    border: var(--ds-border-width) solid var(--ds-color-border);
    font-family: var(--ds-font-mono);
    font-size: var(--ds-text-xs);
    color: var(--ds-color-text-muted);
    white-space: nowrap;
  }
  .sky-live[data-size='sm'] {
    height: 1.75rem;
    padding: 0 var(--ds-space-2-5);
    border-radius: var(--sky-radius-row);
  }
  .sky-live__dot {
    width: 0.4375rem;
    height: 0.4375rem;
    border-radius: var(--ds-radius-full);
    background: var(--ds-color-text-subtle);
  }
  .sky-live[data-size='sm'] .sky-live__dot {
    width: 0.375rem;
    height: 0.375rem;
  }
  .sky-live[data-state='live'] .sky-live__dot,
  .sky-live[data-state='fixtures'] .sky-live__dot {
    background: var(--ds-color-accent);
    box-shadow: 0 0 0 3px var(--sky-color-accent-ring);
  }
  .sky-live[data-state='connecting'] .sky-live__dot {
    background: var(--ds-color-warning);
  }
  @media (prefers-reduced-motion: no-preference) {
    .sky-live[data-state='connecting'] .sky-live__dot {
      animation: sky-live-pulse 1.2s var(--sky-ease-in-out) infinite alternate;
    }
  }
  @keyframes sky-live-pulse {
    to {
      opacity: 0.35;
    }
  }
</style>
