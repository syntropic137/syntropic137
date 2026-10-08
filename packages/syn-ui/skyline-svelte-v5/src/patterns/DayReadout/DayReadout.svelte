<!--
  Day Readout (Main, PhoneOverview, CompPatterns): the pointed or stepped
  Skyline day: sessions, executions, commits, tokens by type and spend.
  Fixed beside the chart on desktop (`dock`), a card under it on a phone
  (`card`, with 44px previous and next buttons).
-->
<script lang="ts">
  import { GLYPH, dayReadout } from '@syn137/skyline-core/patterns'
  import Glyph from '../Glyph/Glyph.svelte'
  import type { DayReadoutProps } from './types'

  let { day, variant = 'dock', position, onprev, onnext, runsHref, ...rest }: DayReadoutProps = $props()

  const r = $derived(day ? dayReadout(day) : null)
</script>

<div {...rest} class="sky-readout" data-variant={variant} role="status" aria-live="polite">
  {#if r}
    {#if variant === 'card'}
      <div class="sky-readout__stepper">
        <button class="sky-readout__step" type="button" aria-label="Previous active day" onclick={onprev}><Glyph d={GLYPH.chevronLeft} weight={1.75} /></button>
        <div class="sky-readout__when">
          <span class="sky-readout__date">{r.dateLabel}</span>
          {#if position}<span class="sky-readout__pos">{position}</span>{/if}
        </div>
        <button class="sky-readout__step" type="button" aria-label="Next active day" onclick={onnext}><Glyph d={GLYPH.chevronRight} weight={1.75} /></button>
      </div>
    {:else}
      <div class="sky-readout__head">
        <span class="sky-readout__date">{r.dateLabel}<span class="sky-readout__year">, {r.year}</span></span>
        {#if runsHref}<a class="sky-readout__runs" href={runsHref}>Runs →</a>{/if}
      </div>
    {/if}
    <dl class="sky-readout__stats">
      <div><dt>Sessions</dt><dd data-accent>{r.sessions}</dd></div>
      <div><dt>Executions</dt><dd>{r.executions}</dd></div>
      <div><dt>Commits</dt><dd>{r.commits}</dd></div>
    </dl>
    <div class="sky-readout__usage">
      <div class="sky-readout__totals">
        <span><span class="sky-readout__k">Tokens</span><span class="sky-readout__v">{r.tokens}</span></span>
        <span><span class="sky-readout__k">Spend</span><span class="sky-readout__v">{r.cost}</span></span>
      </div>
      {#if r.hasTokens}
        <div class="sky-readout__split" aria-hidden="true">
          {#each r.parts as p (p.key)}
            <span style:flex={`${p.flex} 1 0`} style:background={`var(${p.token})`}></span>
          {/each}
        </div>
        <ul class="sky-readout__parts">
          {#each r.parts as p (p.key)}
            <li>
              <span class="sky-readout__swatch" style:background={`var(${p.token})`}></span>
              <span class="sky-readout__part-label">{p.label}</span>
              <span class="sky-readout__part-value">{p.display}</span>
            </li>
          {/each}
        </ul>
      {:else}
        <span class="sky-readout__none">No tokens recorded for this day.</span>
      {/if}
    </div>
    {#if variant === 'card' && runsHref}
      <a class="sky-readout__runs-button" href={runsHref}>Runs that day →</a>
    {/if}
  {:else}
    <span class="sky-readout__none">No activity in this range yet.</span>
  {/if}
</div>

<style>
  .sky-readout {
    display: flex;
    flex-direction: column;
    gap: var(--ds-space-3);
    box-sizing: border-box;
    padding: var(--ds-space-3) var(--ds-space-3-5) var(--ds-space-3-5);
    border-radius: var(--ds-space-4);
    border: var(--ds-border-width) solid var(--sky-color-border-strong);
    background: var(--ds-color-surface-raised);
    box-shadow: var(--sky-shadow-selected);
    color: var(--ds-color-fg);
  }
  .sky-readout[data-variant='dock'] {
    padding: var(--ds-space-3-5) var(--ds-space-4);
    box-shadow: var(--sky-shadow-overlay);
  }
  .sky-readout__head {
    display: flex;
    align-items: baseline;
    justify-content: space-between;
    gap: var(--ds-space-2-5);
  }
  .sky-readout__date {
    font-size: var(--ds-text-lg);
    font-weight: var(--ds-font-weight-semibold);
    letter-spacing: -0.01em;
  }
  .sky-readout__year {
    font-weight: var(--ds-font-weight-regular);
    color: var(--ds-color-text-subtle);
  }
  .sky-readout__runs {
    font-size: var(--sky-text-data);
    font-weight: var(--ds-font-weight-semibold);
    color: var(--sky-color-accent-soft-fg);
    text-decoration: none;
    border-radius: var(--ds-radius-xs);
  }
  .sky-readout__runs:hover {
    text-decoration: underline;
  }
  .sky-readout__stepper {
    display: flex;
    align-items: center;
    gap: var(--ds-space-2-5);
  }
  .sky-readout__step {
    display: flex;
    align-items: center;
    justify-content: center;
    flex-shrink: 0;
    width: var(--sky-size-touch);
    height: var(--sky-size-touch);
    padding: 0;
    border-radius: var(--sky-radius-row);
    border: var(--ds-border-width) solid var(--sky-color-border-strong);
    background: var(--sky-color-control);
    color: var(--ds-color-fg);
    cursor: pointer;
  }
  .sky-readout__step:hover {
    background: var(--sky-color-control-hover);
  }
  .sky-readout__when {
    display: flex;
    flex-direction: column;
    align-items: center;
    flex-grow: 1;
    min-width: 0;
  }
  .sky-readout__pos {
    font-family: var(--ds-font-mono);
    font-size: var(--ds-text-xs);
    color: var(--ds-color-text-subtle);
  }
  .sky-readout__stats {
    display: grid;
    grid-template-columns: repeat(3, minmax(0, 1fr));
    gap: var(--ds-space-2-5);
    margin: 0;
  }
  .sky-readout__stats div {
    display: flex;
    flex-direction: column-reverse;
    gap: 1px;
  }
  .sky-readout__stats dt,
  .sky-readout__k {
    font-family: var(--ds-font-mono);
    font-size: 0.625rem;
    letter-spacing: var(--sky-tracking-label);
    text-transform: uppercase;
    color: var(--ds-color-text-subtle);
  }
  .sky-readout__stats dd {
    margin: 0;
    font-size: 1.375rem;
    line-height: 1.1;
    font-weight: var(--ds-font-weight-semibold);
    letter-spacing: -0.02em;
    font-variant-numeric: tabular-nums;
  }
  .sky-readout__stats dd[data-accent] {
    color: var(--sky-color-accent-soft-fg);
  }
  .sky-readout__usage {
    display: flex;
    flex-direction: column;
    gap: var(--ds-space-2);
    padding-top: var(--ds-space-3);
    border-top: var(--ds-border-width) solid var(--sky-color-border-muted);
  }
  .sky-readout__totals {
    display: flex;
    align-items: baseline;
    justify-content: space-between;
    gap: var(--ds-space-2-5);
  }
  .sky-readout__totals > span {
    display: flex;
    align-items: baseline;
    gap: var(--ds-space-2);
  }
  .sky-readout__v {
    font-family: var(--ds-font-mono);
    font-size: var(--ds-text-sm);
    font-weight: var(--ds-font-weight-semibold);
  }
  .sky-readout__split {
    display: flex;
    gap: 2px;
    height: 0.5rem;
  }
  .sky-readout__split span {
    border-radius: 2px;
  }
  .sky-readout__parts {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 5px var(--ds-space-3-5);
    margin: 0;
    padding: 0;
    list-style: none;
  }
  .sky-readout[data-variant='dock'] .sky-readout__parts {
    grid-template-columns: minmax(0, 1fr);
    gap: var(--ds-space-1);
  }
  .sky-readout__parts li {
    display: flex;
    align-items: center;
    gap: var(--ds-space-1-5);
    font-size: 0.75rem;
    color: var(--ds-color-text-muted);
  }
  .sky-readout__swatch {
    flex-shrink: 0;
    width: 0.5rem;
    height: 0.5rem;
    border-radius: 2px;
  }
  .sky-readout__part-label {
    flex-grow: 1;
    min-width: 0;
  }
  .sky-readout__part-value {
    font-family: var(--ds-font-mono);
    font-size: var(--ds-text-xs);
    color: var(--ds-color-fg);
  }
  .sky-readout__none {
    font-size: var(--sky-text-data);
    color: var(--ds-color-text-muted);
  }
  .sky-readout__runs-button {
    display: flex;
    align-items: center;
    justify-content: center;
    height: var(--sky-size-touch);
    border-radius: var(--sky-radius-control);
    border: var(--ds-border-width) solid var(--sky-color-border-strong);
    background: var(--sky-color-control);
    color: var(--ds-color-fg);
    font-size: var(--ds-text-md);
    font-weight: var(--ds-font-weight-semibold);
    text-decoration: none;
  }
  .sky-readout__runs-button:hover {
    background: var(--sky-color-control-hover);
  }
  .sky-readout__step:focus-visible,
  .sky-readout__runs:focus-visible,
  .sky-readout__runs-button:focus-visible {
    outline: var(--sky-focus-ring-width) solid var(--sky-color-focus);
    outline-offset: var(--sky-focus-ring-offset);
  }
</style>
