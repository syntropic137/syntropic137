<!--
  Run Row (Main, Executions, Workflow, phone boards): status tile, name and
  sub line, phase blocks on a grid shared by the whole list (`slots`, from
  runSlots()) with a duration rule under them, then tokens, cost and age.
  Blocks are one size and phase N sits in the same column on every row
  (owner feedback c80ad278; the boards scaled the blocks with duration).
  A card with the bar under the name on a phone; one grid row from a 40rem
  container. Build `segments`, `barPercent`, `slots` and `sub` with
  runSegments(), runBarPercent(), runSlots() and runSubline().
-->
<script lang="ts">
  import { runBarColumns } from '@syn137/skyline-core/patterns'
  import StatusBadge from '../StatusBadge/StatusBadge.svelte'
  import type { RunRowProps } from './types'

  let { status, name, tag, sub, href, segments, barPercent, slots, duration, tokens, cost, when, ...rest }: RunRowProps = $props()
  const columns = $derived(runBarColumns(segments.length, slots))
</script>

<div class="sky-run-row-host">
  <svelte:element this={href ? 'a' : 'div'} {...rest} class="sky-run-row" {href} data-interactive={href ? true : undefined}>
    <StatusBadge {status} shape="square" />
    <span class="sky-run-row__name">
      <span class="sky-run-row__headline">
        <span class="sky-run-row__title">{name}</span>
        {#if tag}<span class="sky-run-row__tag" title={tag.title}>{tag.label}</span>{/if}
      </span>
      {#if sub}<span class="sky-run-row__sub">{sub}</span>{/if}
    </span>
    <span class="sky-run-row__bar">
      <span class="sky-run-row__track" aria-hidden="true">
        <span class="sky-run-row__cells" style:--_columns={columns}>
          {#each segments as tone, i (i)}
            <span class="sky-run-row__seg" data-tone={tone}></span>
          {/each}
        </span>
        <span class="sky-run-row__time"><span class="sky-run-row__fill" style:width={`${barPercent}%`}></span></span>
      </span>
      <span class="sky-run-row__duration">{duration}</span>
    </span>
    <span class="sky-run-row__tokens">{tokens ?? ''}</span>
    <span class="sky-run-row__money">
      <span class="sky-run-row__cost">{cost ?? ''}</span>
      <span class="sky-run-row__when">{when ?? ''}</span>
    </span>
  </svelte:element>
</div>

<style>
  .sky-run-row-host {
    container-type: inline-size;
    min-width: 0;
  }
  .sky-run-row {
    display: grid;
    grid-template-columns: auto minmax(0, 1fr) auto;
    grid-template-areas:
      'badge name money'
      'bar bar bar';
    align-items: center;
    gap: var(--ds-space-2-5) var(--ds-space-3);
    padding: var(--ds-space-3-5);
    border-radius: var(--sky-radius-xl);
    border: var(--ds-border-width) solid var(--ds-color-border);
    background: var(--ds-color-surface);
    color: var(--ds-color-fg);
    text-decoration: none;
  }
  .sky-run-row[data-interactive]:hover {
    border-color: var(--sky-color-border-hover);
  }
  .sky-run-row:focus-visible {
    outline: var(--sky-focus-ring-width) solid var(--sky-color-focus);
    outline-offset: var(--sky-focus-ring-offset);
  }
  .sky-run-row > :global(.sky-status) {
    grid-area: badge;
  }
  .sky-run-row__name {
    grid-area: name;
    display: flex;
    flex-direction: column;
    min-width: 0;
  }
  .sky-run-row__headline {
    display: flex;
    align-items: center;
    gap: var(--ds-space-1-5);
    min-width: 0;
  }
  .sky-run-row__tag {
    flex-shrink: 0;
    padding: 0 var(--ds-space-1-5);
    border-radius: var(--ds-radius-full);
    border: var(--ds-border-width) solid var(--sky-color-accent-ring);
    background: var(--sky-color-accent-soft);
    color: var(--sky-color-accent-soft-fg);
    font-family: var(--ds-font-mono);
    font-size: var(--ds-text-xs);
    line-height: 1.125rem;
  }
  .sky-run-row__title {
    font-size: var(--sky-text-body);
    font-weight: var(--ds-font-weight-semibold);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .sky-run-row__sub {
    font-family: var(--ds-font-mono);
    font-size: var(--ds-text-xs);
    color: var(--ds-color-text-subtle);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .sky-run-row__bar {
    grid-area: bar;
    display: flex;
    align-items: center;
    gap: var(--ds-space-2-5);
    min-width: 0;
  }
  .sky-run-row__track {
    display: flex;
    flex-direction: column;
    gap: 3px;
    flex-grow: 1;
    min-width: 0;
  }
  .sky-run-row__cells {
    display: grid;
    grid-template-columns: repeat(var(--_columns), minmax(0, 1fr));
    gap: 2px;
    height: 0.625rem;
  }
  .sky-run-row__time {
    display: block;
    height: 2px;
    border-radius: 1px;
    background: var(--sky-color-track);
  }
  .sky-run-row__fill {
    display: block;
    height: 100%;
    border-radius: 1px;
    background: var(--ds-color-text-subtle);
  }
  .sky-run-row__seg {
    height: 100%;
    border-radius: 3px;
    background: var(--sky-color-empty);
  }
  .sky-run-row__seg[data-tone='done'] {
    background: var(--sky-status-completed);
  }
  .sky-run-row__seg[data-tone='failed'] {
    background: var(--sky-status-failed);
  }
  .sky-run-row__seg[data-tone='cancelled'] {
    background: var(--sky-status-cancelled);
  }
  .sky-run-row__seg[data-tone='running'] {
    background: var(--sky-color-running-block);
  }
  @media (prefers-reduced-motion: no-preference) {
    .sky-run-row__seg[data-tone='running'] {
      animation: sky-run-pulse 1.4s var(--sky-ease-in-out) infinite alternate;
    }
  }
  /* Opacity, not colour: interpolating a color-mix() background misrenders in Chromium. */
  @keyframes sky-run-pulse {
    to {
      opacity: 0.45;
    }
  }
  .sky-run-row__duration {
    width: 3.25rem;
    flex-shrink: 0;
    text-align: right;
    font-family: var(--ds-font-mono);
    font-size: var(--ds-text-xs);
    color: var(--ds-color-text-muted);
  }
  .sky-run-row__tokens {
    display: none;
  }
  .sky-run-row__money {
    grid-area: money;
    display: flex;
    flex-direction: column;
    align-items: flex-end;
    font-family: var(--ds-font-mono);
  }
  .sky-run-row__cost {
    font-size: var(--ds-text-sm);
  }
  .sky-run-row__when {
    font-size: var(--ds-text-xs);
    color: var(--ds-color-text-subtle);
  }

  @container (min-width: 40rem) {
    .sky-run-row {
      grid-template-columns: var(--sky-size-control-sm) minmax(10rem, 1.1fr) minmax(10rem, 1.5fr) 4.5rem 4rem 4rem;
      grid-template-areas: none;
      column-gap: var(--ds-space-4);
      padding: var(--ds-space-3);
      border-color: transparent;
      border-radius: var(--sky-radius-row);
      background: transparent;
    }
    .sky-run-row[data-interactive]:hover {
      border-color: transparent;
      background: var(--ds-color-surface-raised);
    }
    .sky-run-row > :global(.sky-status),
    .sky-run-row__name,
    .sky-run-row__bar {
      grid-area: auto;
    }
    .sky-run-row__title {
      font-size: var(--ds-text-md);
    }
    .sky-run-row__duration {
      text-align: left;
      font-size: var(--ds-text-xs);
    }
    .sky-run-row__tokens,
    .sky-run-row__cost,
    .sky-run-row__when {
      display: block;
      text-align: right;
      font-family: var(--ds-font-mono);
      font-size: var(--sky-text-data);
    }
    .sky-run-row__tokens {
      color: var(--ds-color-text-muted);
    }
    .sky-run-row__when {
      font-size: var(--ds-text-xs);
    }
    .sky-run-row__money {
      display: contents;
    }
  }
  @media (pointer: coarse) {
    .sky-run-row {
      min-height: var(--sky-size-touch);
    }
  }
</style>
