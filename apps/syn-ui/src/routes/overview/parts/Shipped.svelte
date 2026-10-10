<!--
  Shipped by agents (Main and PhoneOverview boards): five window totals,
  each with a delta chip against the window before and a daily bar
  sparkline. Values come from skyline-core shippedTiles(); this only renders.
  A tile the server cannot answer says so, never a fake zero.
-->
<script lang="ts">
  import GitCommit from '@lucide/svelte/icons/git-commit-horizontal'
  import { shippedBarRects, shippedWindowLine, type ShippedTile } from '@syn137/skyline-core/screens/overview'
  import { href } from '../../../lib/router'

  let { tiles, days }: { tiles: ShippedTile[]; days: number } = $props()
  const windowLine = $derived(shippedWindowLine(days))

  const SPARK_H = 26
</script>

<section class="sky-ov-shipped" aria-label="Shipped by agents, last {days} days">
  <div class="sky-ov-shipped__head">
    <h3><GitCommit size={15} aria-hidden="true" />Shipped by agents</h3>
    <span class="sky-ov-shipped__window">{windowLine} · <a href={href('/executions')}>by workflow →</a></span>
  </div>
  <ul class="sky-ov-shipped__tiles">
    {#each tiles as t (t.key)}
      <li class="sky-ov-shipped__tile" data-available={t.available}>
        <span class="sky-ov-shipped__label">{t.label}</span>
        {#if t.available}
          <span class="sky-ov-shipped__figure" aria-label={t.summary}>
            <span class="sky-ov-shipped__total" aria-hidden="true">{t.total}</span>
            <span class="sky-ov-shipped__delta" data-tone={t.tone} aria-hidden="true">{t.delta}</span>
          </span>
          <svg class="sky-ov-shipped__spark" viewBox="0 0 {Math.max(1, t.bars.length * 10 - 2)} {SPARK_H}" preserveAspectRatio="none" aria-hidden="true">
            {#each shippedBarRects(t.bars, SPARK_H) as r, i (t.bars[i]!.date)}
              <rect x={r.x} y={r.y} width={r.width} height={r.height} rx="1" data-state={t.bars[i]!.empty ? 'empty' : t.bars[i]!.current ? 'current' : undefined} />
            {/each}
          </svg>
        {:else}
          <span class="sky-ov-shipped__na" title={t.reason ?? undefined}>Not available on this server</span>
        {/if}
      </li>
    {/each}
  </ul>
</section>

<style>
  .sky-ov-shipped {
    display: flex;
    flex-direction: column;
    gap: var(--ds-space-2-5);
    margin-top: var(--ds-space-2);
    padding: var(--ds-space-3-5);
    border-radius: var(--sky-radius-xl);
    border: var(--ds-border-width) solid var(--ds-color-border);
    background: var(--ds-color-surface);
    container-type: inline-size;
    min-width: 0;
  }
  .sky-ov-shipped__head {
    display: flex;
    flex-wrap: wrap;
    align-items: baseline;
    justify-content: space-between;
    gap: var(--ds-space-1-5) var(--ds-space-4);
  }
  h3 {
    display: flex;
    align-items: center;
    gap: var(--ds-space-2);
    margin: 0;
    font-size: var(--sky-text-body);
    font-weight: var(--ds-font-weight-semibold);
  }
  h3 :global(svg) {
    color: var(--ds-color-accent);
    align-self: center;
  }
  .sky-ov-shipped__window {
    font-size: var(--ds-text-sm);
    color: var(--ds-color-text-muted);
  }
  .sky-ov-shipped__window a {
    color: var(--ds-color-fg);
    text-decoration: none;
  }
  .sky-ov-shipped__window a:hover {
    text-decoration: underline;
  }
  .sky-ov-shipped__window a:focus-visible {
    outline: var(--sky-focus-ring-width) solid var(--sky-color-focus);
    outline-offset: var(--sky-focus-ring-offset);
  }
  @media (pointer: coarse) {
    .sky-ov-shipped__window a {
      display: inline-flex;
      align-items: center;
      min-height: var(--sky-size-touch);
    }
  }
  .sky-ov-shipped__tiles {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: var(--ds-space-2);
    margin: 0;
    padding: 0;
    list-style: none;
  }
  .sky-ov-shipped__tile {
    display: flex;
    flex-direction: column;
    gap: var(--ds-space-2);
    min-width: 0;
    padding: var(--ds-space-3);
    border-radius: var(--sky-radius-row);
    border: var(--ds-border-width) solid var(--ds-color-border);
    background: var(--ds-color-bg);
  }
  .sky-ov-shipped__label {
    font-size: var(--ds-text-xs);
    color: var(--ds-color-text-muted);
  }
  .sky-ov-shipped__figure {
    display: flex;
    flex-wrap: wrap;
    align-items: baseline;
    gap: 0 var(--ds-space-2);
  }
  .sky-ov-shipped__total {
    font-size: var(--ds-text-xl);
    font-weight: var(--ds-font-weight-semibold);
    letter-spacing: var(--sky-tracking-title);
    font-variant-numeric: tabular-nums;
    line-height: var(--ds-line-height-tight);
  }
  .sky-ov-shipped__delta {
    font-family: var(--ds-font-mono);
    font-size: var(--sky-text-label);
    color: var(--ds-color-text-subtle);
  }
  .sky-ov-shipped__delta[data-tone='better'] {
    color: var(--sky-color-success-soft-fg);
  }
  .sky-ov-shipped__delta[data-tone='worse'] {
    color: var(--sky-color-danger-soft-fg);
  }
  .sky-ov-shipped__spark {
    display: block;
    width: 100%;
    height: 26px;
  }
  .sky-ov-shipped__spark rect {
    fill: color-mix(in oklab, var(--ds-color-accent) 45%, var(--sky-color-track));
  }
  .sky-ov-shipped__spark rect[data-state='current'] {
    fill: var(--ds-color-accent);
  }
  .sky-ov-shipped__spark rect[data-state='empty'] {
    fill: var(--ds-color-border);
  }
  .sky-ov-shipped__na {
    flex-grow: 1;
    display: flex;
    align-items: center;
    min-height: calc(26px + var(--ds-space-2) + 1.5rem);
    font-size: var(--ds-text-xs);
    color: var(--ds-color-text-subtle);
  }

  @container (min-width: 40rem) {
    .sky-ov-shipped__tiles {
      grid-template-columns: repeat(5, minmax(0, 1fr));
    }
    .sky-ov-shipped__tile {
      padding: var(--ds-space-3-5) var(--ds-space-4);
    }
  }
  @media (min-width: 48rem) {
    .sky-ov-shipped {
      padding: var(--ds-space-4);
    }
  }
</style>
