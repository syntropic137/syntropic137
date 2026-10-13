<!--
  Usage Band (UsageMeter board; Landing pillar 03 and "What it is"): tokens
  by type as one strip, one segment per non-empty series in TOKEN_SERIES
  order, with a legend. The Usage Meter renders its token zone with it.
  `shape="flat"` is the landing's plain bar; `legend="compact"` shows
  swatches and names only.
-->
<script lang="ts">
  import { TOKEN_SERIES } from '@syn137/skyline-core/format'
  import { extrudeColors, layoutUsageBand } from '@syn137/skyline-core/geometry'
  import { usageBand } from '@syn137/skyline-core/patterns'
  import type { UsageBandProps } from './types'
  import { USAGE_BAND_LEGEND, USAGE_BAND_SHAPE } from './variants'

  let { tokens, rates, shape = 'extruded', legend = 'full', ...rest }: UsageBandProps = $props()

  const m = $derived(usageBand({ tokens, rates }))
  const band = $derived(layoutUsageBand(TOKEN_SERIES.map((s) => ({ key: s.key, value: tokens[s.key] }))))
  const colour = (key: string) => {
    const s = TOKEN_SERIES.find((x) => x.key === key)
    return extrudeColors(`var(${s?.token ?? '--ds-color-accent'})`)
  }
</script>

<div {...rest} class="sky-usage-band" data-shape={USAGE_BAND_SHAPE[shape]} data-legend={USAGE_BAND_LEGEND[legend]}>
  {#if band.segments.length}
    {#if shape === 'flat'}
      <span class="sky-usage-band__flat" part="band" role="img" aria-label={m.bandLabel}>
        {#each m.series as s (s.key)}
          <span style:flex-grow={s.value} style:background={`var(${s.token})`}></span>
        {/each}
      </span>
    {:else}
      <svg class="sky-usage-band__band" part="band" viewBox={band.viewBox} preserveAspectRatio="none" role="img" aria-label={m.bandLabel}>
        {#each band.segments as s (s.key)}
          {@const f = colour(s.key)}
          <path d={s.paths.side} style:fill={f.side} />
          <path d={s.paths.top} style:fill={f.top} />
          <path d={s.paths.front} style:fill={f.front} />
        {/each}
      </svg>
    {/if}
    {#if legend === 'full'}
      <ul class="sky-usage-band__legend" part="legend">
        {#each m.series as s (s.key)}
          <li>
            <span class="sky-usage-band__series">
              <span class="sky-usage-band__swatch" style:background={`var(${s.token})`}></span>{s.label}
              {#if s.rate}<span class="sky-usage-band__rate">{s.rate}</span>{/if}
            </span>
            <span class="sky-usage-band__figure"><span class="sky-usage-band__count">{s.display}</span><span class="sky-usage-band__pct">{s.percent}</span></span>
          </li>
        {/each}
      </ul>
    {:else if legend === 'compact'}
      <ul class="sky-usage-band__keys" part="legend">
        {#each m.series as s (s.key)}
          <li><span class="sky-usage-band__swatch" style:background={`var(${s.token})`}></span>{s.label}</li>
        {/each}
      </ul>
    {/if}
  {:else}
    <span class="sky-usage-band__empty">No tokens recorded.</span>
  {/if}
</div>

<style>
  .sky-usage-band {
    display: flex;
    flex-direction: column;
    gap: var(--ds-space-3);
    min-width: 0;
  }
  .sky-usage-band__band {
    display: block;
    width: 100%;
    height: 2.125rem;
  }
  .sky-usage-band__flat {
    display: flex;
    gap: 2px;
    height: 1.375rem;
  }
  .sky-usage-band__flat > span {
    flex: 1 1 0;
    min-width: 4px;
  }
  .sky-usage-band__flat > span:first-child {
    border-start-start-radius: 6px;
    border-end-start-radius: 6px;
  }
  .sky-usage-band__flat > span:last-child {
    border-start-end-radius: 6px;
    border-end-end-radius: 6px;
  }
  .sky-usage-band__legend {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(7.375rem, 1fr));
    gap: var(--ds-space-3) var(--ds-space-4);
    margin: 0;
    padding: 0;
    list-style: none;
  }
  .sky-usage-band__legend li {
    display: flex;
    flex-direction: column;
    gap: 3px;
    min-width: 0;
  }
  .sky-usage-band__series {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: var(--ds-space-1) 7px;
    font-size: var(--sky-text-data);
    color: var(--ds-color-text-muted);
  }
  .sky-usage-band__swatch {
    flex-shrink: 0;
    width: 0.5rem;
    height: 0.5rem;
    border-radius: 2px;
  }
  .sky-usage-band__rate {
    padding: 1px 6px;
    border-radius: 6px;
    border: var(--ds-border-width) solid var(--sky-color-border-strong);
    font-family: var(--ds-font-mono);
    font-size: var(--sky-text-label);
  }
  .sky-usage-band__figure {
    display: flex;
    align-items: baseline;
    gap: 7px;
    font-family: var(--ds-font-mono);
  }
  .sky-usage-band__count {
    font-size: 0.84375rem;
    font-weight: var(--ds-font-weight-semibold);
  }
  .sky-usage-band__pct {
    font-size: var(--ds-text-xs);
    color: var(--ds-color-text-muted);
  }
  .sky-usage-band__keys {
    display: flex;
    flex-wrap: wrap;
    gap: 6px var(--ds-space-4);
    margin: 0;
    padding: 0;
    list-style: none;
    font-size: var(--ds-text-xs);
    color: var(--ds-color-text-muted);
  }
  .sky-usage-band__keys li {
    display: flex;
    align-items: center;
    gap: 6px;
  }
  .sky-usage-band__keys .sky-usage-band__swatch {
    width: 9px;
    height: 9px;
  }
  .sky-usage-band__empty {
    margin: 0;
    font-size: var(--sky-text-data);
    line-height: var(--ds-line-height-normal);
    color: var(--ds-color-text-muted);
  }
</style>
