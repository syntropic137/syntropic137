<!--
  Lineage Trail (Artifact board, CompPatterns): workflow to execution to
  phase to session as linked chips with arrows. Scrolls sideways in its own
  box on a phone instead of wrapping.
-->
<script lang="ts">
  import type { LineageTrailProps } from './types'

  let { steps, ...rest }: LineageTrailProps = $props()
</script>

<nav {...rest} class="sky-lineage" aria-label={rest['aria-label'] ?? 'Lineage'}>
  <ol class="sky-lineage__list">
    {#each steps as s, i (i)}
      <li class="sky-lineage__step">
        {#if i > 0}<span class="sky-lineage__arrow" aria-hidden="true">→</span>{/if}
        <svelte:element this={s.href ? 'a' : 'span'} class="sky-lineage__chip" href={s.href} data-link={s.href ? true : undefined}>
          <span class="sky-lineage__kind">{s.kind}</span>
          <span class="sky-lineage__value">{s.value}</span>
        </svelte:element>
      </li>
    {/each}
  </ol>
</nav>

<style>
  .sky-lineage {
    min-width: 0;
    max-width: 100%;
    overflow-x: auto;
    scrollbar-width: thin;
  }
  .sky-lineage__list {
    display: flex;
    align-items: center;
    gap: var(--ds-space-2);
    margin: 0;
    padding: 2px;
    list-style: none;
    width: max-content;
  }
  @media (min-width: 48rem) {
    .sky-lineage__list {
      flex-wrap: wrap;
      width: auto;
    }
  }
  .sky-lineage__step {
    display: flex;
    align-items: center;
    gap: var(--ds-space-2);
  }
  .sky-lineage__arrow {
    color: var(--ds-color-text-subtle);
  }
  .sky-lineage__chip {
    display: flex;
    align-items: baseline;
    gap: var(--ds-space-2);
    height: 1.875rem;
    padding: 0 var(--ds-space-3);
    border-radius: var(--ds-radius-full);
    border: var(--ds-border-width) solid var(--ds-color-border);
    line-height: 1.75rem;
    color: var(--ds-color-fg);
    text-decoration: none;
    white-space: nowrap;
  }
  .sky-lineage__chip[data-link] {
    border-color: var(--sky-color-border-strong);
    background: var(--ds-color-bg);
  }
  .sky-lineage__chip[data-link]:hover {
    border-color: var(--sky-color-border-hover);
  }
  .sky-lineage__chip:focus-visible {
    outline: var(--sky-focus-ring-width) solid var(--sky-color-focus);
    outline-offset: var(--sky-focus-ring-offset);
  }
  .sky-lineage__kind {
    font-size: 0.75rem;
    color: var(--ds-color-text-subtle);
  }
  .sky-lineage__value {
    font-family: var(--ds-font-mono);
    font-size: 0.75rem;
  }
  @media (pointer: coarse) {
    .sky-lineage__chip[data-link] {
      height: var(--sky-size-touch);
      line-height: calc(var(--sky-size-touch) - 2px);
    }
  }
</style>
