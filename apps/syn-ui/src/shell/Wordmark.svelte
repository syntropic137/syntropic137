<!-- Syntropic137 wordmark: the S mark (SMark, eleven isometric cubes from skyline-core's sMark()) and Orbitron type, as in the
     landing nav. The S is 21px wide (44px tall, about 1:2.1): the tallest it gets without growing the 44px top bar row. -->
<script lang="ts">
  import { SMark } from '@syn137/skyline-svelte-v5/patterns'

  let { href = '/', compact = false }: { href?: string; compact?: boolean } = $props()
</script>

<a class="sky-wordmark" data-compact={compact || undefined} {href} aria-label="Syntropic137 overview">
  <span class="sky-wordmark__mark"><SMark size={21} label="" /></span>
  <span class="sky-wordmark__text">Syntropic<span class="sky-wordmark__num">137</span></span>
</a>

<style>
  .sky-wordmark {
    display: flex;
    align-items: center;
    gap: var(--ds-space-2-5);
    min-height: var(--sky-size-touch);
    border-radius: var(--ds-radius-md);
    text-decoration: none;
    color: var(--ds-color-fg);
  }
  .sky-wordmark:focus-visible {
    outline: var(--sky-focus-ring-width) solid var(--sky-color-focus);
    outline-offset: var(--sky-focus-ring-offset);
  }
  .sky-wordmark__mark {
    display: block;
    flex: none;
  }
  .sky-wordmark__text {
    font-family: var(--sky-font-brand);
    font-size: var(--ds-text-sm);
    font-weight: var(--ds-font-weight-semibold);
    letter-spacing: var(--sky-tracking-brand);
    white-space: nowrap;
  }
  .sky-wordmark__num {
    color: var(--ds-color-accent);
  }
  @media (min-width: 48rem) {
    .sky-wordmark:not([data-compact]) .sky-wordmark__text {
      font-size: var(--ds-text-md);
    }
  }
</style>
