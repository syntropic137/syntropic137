<!-- Stat (CompDisplay board): label above a tabular figure; unknown shows a muted dash. -->
<script lang="ts">
  import { UNKNOWN } from '@syn137/skyline-core/format'
  import type { StatProps } from './types'

  let { label, value, size = 'md', meta, children, ...rest }: StatProps = $props()

  const unknown = $derived(!children && (value === null || value === undefined || value === '' || value === UNKNOWN))
</script>

<div {...rest} class="sky-stat" data-size={size}>
  <span class="sky-stat__label">{label}</span>
  <span class="sky-stat__value" data-unknown={unknown || undefined}>
    {#if children}{@render children()}{:else if unknown}{UNKNOWN}{:else}{value}{/if}
  </span>
  {#if meta}<span class="sky-stat__meta">{@render meta()}</span>{/if}
</div>

<style>
  .sky-stat {
    display: flex;
    flex-direction: column;
    gap: var(--ds-space-0-5);
    min-width: 0;
  }
  .sky-stat__label {
    font-family: var(--ds-font-mono);
    font-size: var(--sky-text-label);
    letter-spacing: var(--sky-tracking-label);
    text-transform: uppercase;
    color: var(--ds-color-text-subtle);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .sky-stat__value {
    display: flex;
    align-items: baseline;
    gap: var(--ds-space-1-5);
    font-size: var(--sky-text-figure);
    line-height: 1.1;
    font-weight: var(--ds-font-weight-semibold);
    letter-spacing: -0.03em;
    font-variant-numeric: tabular-nums;
    color: var(--ds-color-fg);
    overflow-wrap: anywhere;
  }
  .sky-stat[data-size='hero'] .sky-stat__value {
    font-size: clamp(var(--sky-text-3xl), 1.4rem + 1.2vw, 2.375rem);
  }
  .sky-stat[data-size='sm'] .sky-stat__value {
    font-size: var(--ds-text-xl);
    letter-spacing: -0.02em;
  }
  .sky-stat__value[data-unknown] {
    color: var(--ds-color-text-subtle);
  }
  .sky-stat__meta {
    font-size: var(--sky-text-data);
    color: var(--ds-color-text-muted);
  }
</style>
