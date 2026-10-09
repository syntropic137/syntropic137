<!--
  Usage Meter (UsageMeter board): what a session, execution or day spent.
  Total cost and tokens, an extruded band of tokens by type with a legend,
  and cost by model or by phase. Zones wrap from a wide strip into one
  column, so the same block fits a page, a side column or a phone.
-->
<script lang="ts">
  import { usageModel } from '@syn137/skyline-core/patterns'
  import UsageBand from '../UsageBand/UsageBand.svelte'
  import type { UsageMeterProps } from './types'

  let { cost, tokens, costRows, costBy, note, rates, title = 'Usage', ...rest }: UsageMeterProps = $props()

  const m = $derived(usageModel({ cost, tokens, costRows, costBy, rates }))
</script>

<section {...rest} class="sky-usage" aria-label={rest['aria-label'] ?? title}>
  <div class="sky-usage__total">
    <h2 class="sky-usage__heading">{title}</h2>
    <span class="sky-usage__cost">{m.cost}</span>
    <span class="sky-usage__tokens">{m.tokensLabel}</span>
  </div>

  <div class="sky-usage__zone" data-zone="tokens">
    <span class="sky-usage__label">Tokens by type</span>
    <UsageBand {tokens} {rates} />
  </div>

  <div class="sky-usage__zone" data-zone="cost">
    <span class="sky-usage__label">Cost by {costBy}</span>
    <ul class="sky-usage__rows">
      {#each m.costRows as r, i (i)}
        <li class="sky-usage__row">
          <span class="sky-usage__row-label">{r.label}</span>
          <span class="sky-usage__bar" aria-hidden="true"><span data-tone={r.tone} style:width={`${r.fill}%`}></span></span>
          <span class="sky-usage__row-value">{r.display} <span class="sky-usage__pct">{r.percent}</span></span>
        </li>
      {/each}
    </ul>
    {#if note}<p class="sky-usage__note">{note}</p>{/if}
  </div>
</section>

<style>
  .sky-usage {
    display: flex;
    flex-wrap: wrap;
    align-items: stretch;
    gap: var(--ds-space-5) var(--ds-space-10);
    padding: var(--ds-space-5);
    border-radius: var(--sky-radius-card-lg);
    border: var(--ds-border-width) solid var(--ds-color-border);
    background: var(--ds-color-surface);
    box-shadow: var(--sky-shadow-raised);
  }
  @media (min-width: 48rem) {
    .sky-usage {
      padding: var(--ds-space-6) var(--ds-space-7);
    }
  }
  .sky-usage__total {
    flex: 0 1 10.625rem;
    display: flex;
    flex-direction: column;
    gap: var(--ds-space-1);
    min-width: 0;
  }
  .sky-usage__heading,
  .sky-usage__label {
    margin: 0;
    font-family: var(--ds-font-mono);
    font-size: var(--sky-text-label);
    font-weight: var(--ds-font-weight-medium);
    letter-spacing: var(--sky-tracking-label);
    text-transform: uppercase;
    color: var(--ds-color-text-subtle);
  }
  .sky-usage__cost {
    font-size: 2rem;
    line-height: 1.1;
    font-weight: var(--ds-font-weight-semibold);
    letter-spacing: -0.03em;
    font-variant-numeric: tabular-nums;
  }
  .sky-usage__tokens {
    font-family: var(--ds-font-mono);
    font-size: var(--sky-text-data);
    color: var(--ds-color-text-muted);
  }
  .sky-usage__zone {
    display: flex;
    flex-direction: column;
    gap: var(--ds-space-3);
    min-width: 0;
  }
  .sky-usage__zone[data-zone='tokens'] {
    flex: 3 1 18.75rem;
  }
  .sky-usage__zone[data-zone='cost'] {
    flex: 2 1 16.25rem;
  }
  .sky-usage__pct {
    font-size: var(--ds-text-xs);
    color: var(--ds-color-text-muted);
  }
  .sky-usage__rows {
    display: flex;
    flex-direction: column;
    gap: var(--ds-space-2-5);
    margin: 0;
    padding: 0;
    list-style: none;
  }
  .sky-usage__row {
    display: grid;
    grid-template-columns: minmax(0, 1.2fr) minmax(2.5rem, 1fr) auto;
    column-gap: var(--ds-space-3);
    align-items: center;
    font-family: var(--ds-font-mono);
    font-size: var(--sky-text-data);
  }
  .sky-usage__row-label {
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .sky-usage__bar {
    display: block;
    height: 6px;
    border-radius: 3px;
    background: var(--ds-color-overlay);
  }
  .sky-usage__bar span {
    display: block;
    height: 100%;
    border-radius: 3px;
    background: color-mix(in oklab, var(--ds-color-text-muted) 75%, var(--ds-color-text-subtle));
  }
  .sky-usage__bar span[data-tone='accent'] {
    background: var(--ds-color-accent);
  }
  .sky-usage__bar span[data-tone='claude'] {
    background: var(--sky-color-agent-claude);
  }
  .sky-usage__bar span[data-tone='codex'] {
    background: var(--sky-color-agent-codex);
  }
  .sky-usage__row-value {
    text-align: right;
    white-space: nowrap;
  }
  .sky-usage__note {
    margin: 0;
    font-size: var(--sky-text-data);
    line-height: var(--ds-line-height-normal);
    color: var(--ds-color-text-muted);
  }
</style>
