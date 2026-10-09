<!-- Token mix card: one stacked bar plus a legend, series colours from TOKEN_SERIES. -->
<script lang="ts">
  import { formatTokens } from '@syn137/skyline-core/format'
  import type { TokenMixPart } from '@syn137/skyline-core/screens/overview'

  let { total, parts }: { total: number; parts: TokenMixPart[] } = $props()

  const summary = $derived(parts.map((p) => `${p.label} ${p.share}`).join(', '))
</script>

<section class="sky-ov-card" aria-labelledby="sky-ov-mix-title">
  <div class="sky-ov-card__head">
    <h2 id="sky-ov-mix-title">Token mix</h2>
    <span class="sky-ov-mono">{formatTokens(total)}</span>
  </div>
  {#if parts.length === 0}
    <p class="sky-ov-mix__empty">No tokens recorded yet.</p>
  {:else}
    <div class="sky-ov-mix__bar" role="img" aria-label={summary}>
      {#each parts as p (p.key)}
        <span style:flex="{p.flex} 1 0" style:background="var({p.token})"></span>
      {/each}
    </div>
    <ul class="sky-ov-mix__legend">
      {#each parts as p (p.key)}
        <li>
          <span class="sky-ov-mix__swatch" style:background="var({p.token})"></span>
          <span class="sky-ov-mix__label">{p.label}</span>
          <span class="sky-ov-mono" data-tone="fg">{p.display}</span>
          <span class="sky-ov-mono sky-ov-mix__share">{p.share}</span>
        </li>
      {/each}
    </ul>
  {/if}
</section>

<style>
  .sky-ov-mix__bar {
    display: flex;
    gap: 2px;
    height: 14px;
  }
  .sky-ov-mix__bar span {
    min-width: 2px;
    box-shadow: var(--sky-shadow-raised);
  }
  .sky-ov-mix__bar span:first-child {
    border-start-start-radius: var(--ds-radius-sm);
    border-end-start-radius: var(--ds-radius-sm);
  }
  .sky-ov-mix__bar span:last-child {
    border-start-end-radius: var(--ds-radius-sm);
    border-end-end-radius: var(--ds-radius-sm);
  }
  .sky-ov-mix__legend {
    display: flex;
    flex-direction: column;
    gap: var(--ds-space-2);
    margin: 0;
    padding: 0;
    list-style: none;
    font-size: var(--ds-text-sm);
  }
  .sky-ov-mix__legend li {
    display: flex;
    align-items: center;
    gap: var(--ds-space-2-5);
  }
  .sky-ov-mix__swatch {
    width: 8px;
    height: 8px;
    border-radius: 2px;
    flex-shrink: 0;
  }
  .sky-ov-mix__label {
    flex-grow: 1;
    color: var(--ds-color-text-muted);
  }
  .sky-ov-mix__share {
    width: 3rem;
    text-align: right;
    color: var(--ds-color-text-subtle);
  }
  .sky-ov-mix__empty {
    margin: 0;
    font-size: var(--ds-text-sm);
    color: var(--ds-color-text-muted);
  }
</style>
