<!--
  "From trigger to artifact": the five objects Syn137 keeps. Phone: a list of
  rows (PhoneOverview). From 48rem: a grid of numbered cards (Main).
-->
<script lang="ts">
  import { ObjectIcon } from '@syn137/skyline-svelte-v5/patterns'
  import { href } from '../../../lib/router'
  import type { PipelineItem } from './types'

  let { items }: { items: PipelineItem[] } = $props()
</script>

<section class="sky-ov-pipe" aria-labelledby="sky-ov-pipe-title">
  <div class="sky-ov-pipe__head">
    <h2 id="sky-ov-pipe-title">From trigger to artifact</h2>
    <p>The five things Syn137 keeps, in the order work moves through them.</p>
  </div>
  <ol class="sky-ov-pipe__list">
    {#each items as it, i (it.kind)}
      <li>
        <a class="sky-ov-pipe__item" href={href(it.path)}>
          <span class="sky-ov-pipe__icon">
            <ObjectIcon kind={it.kind} size={64} />
            <span class="sky-ov-pipe__step" aria-hidden="true">{String(i + 1).padStart(2, '0')}</span>
          </span>
          <span class="sky-ov-pipe__text">
            <span class="sky-ov-pipe__count">{it.count}</span>
            <span class="sky-ov-pipe__label">{it.label}</span>
            <span class="sky-ov-pipe__sub" data-size="long">{it.sub}</span>
            <span class="sky-ov-pipe__sub" data-size="short">{it.subShort}</span>
          </span>
        </a>
      </li>
    {/each}
  </ol>
</section>

<style>
  .sky-ov-pipe {
    display: flex;
    flex-direction: column;
    gap: var(--ds-space-2);
  }
  .sky-ov-pipe__head {
    display: flex;
    flex-wrap: wrap;
    align-items: baseline;
    gap: var(--ds-space-1) var(--ds-space-3);
  }
  .sky-ov-pipe__head h2 {
    margin: 0;
    font-size: var(--ds-text-lg);
    font-weight: var(--ds-font-weight-semibold);
    letter-spacing: var(--sky-tracking-title);
  }
  .sky-ov-pipe__head p {
    display: none;
    margin: 0;
    font-size: var(--ds-text-md);
    color: var(--ds-color-text-muted);
  }
  .sky-ov-pipe__list {
    display: flex;
    flex-direction: column;
    margin: 0;
    padding: 0;
    list-style: none;
  }
  .sky-ov-pipe__item {
    display: flex;
    align-items: center;
    gap: var(--ds-space-3-5);
    min-height: 4rem;
    padding: var(--ds-space-1) var(--ds-space-3);
    border-radius: var(--sky-radius-row);
    color: var(--ds-color-fg);
    text-decoration: none;
  }
  .sky-ov-pipe__item:hover {
    background: var(--ds-color-surface);
    color: var(--ds-color-fg);
  }
  .sky-ov-pipe__item:focus-visible {
    outline: var(--sky-focus-ring-width) solid var(--sky-color-focus);
    outline-offset: var(--sky-focus-ring-offset);
  }
  .sky-ov-pipe__icon {
    display: flex;
    flex-shrink: 0;
    align-items: flex-start;
    justify-content: space-between;
    width: 2.75rem;
  }
  .sky-ov-pipe__icon :global(svg) {
    width: 2.75rem;
    height: 2.75rem;
  }
  .sky-ov-pipe__step {
    display: none;
    font-family: var(--ds-font-mono);
    font-size: var(--sky-text-label);
    color: var(--ds-color-text-subtle);
  }
  .sky-ov-pipe__text {
    display: grid;
    flex: 1 1 auto;
    grid-template-columns: minmax(0, 1fr) auto;
    grid-template-areas: 'label count' 'sub count';
    align-items: center;
    column-gap: var(--ds-space-3);
    min-width: 0;
  }
  .sky-ov-pipe__label {
    grid-area: label;
    font-weight: var(--ds-font-weight-semibold);
  }
  .sky-ov-pipe__count {
    grid-area: count;
    font-size: var(--ds-text-2xl);
    font-weight: var(--ds-font-weight-semibold);
    letter-spacing: var(--sky-tracking-title);
    font-variant-numeric: tabular-nums;
  }
  .sky-ov-pipe__sub {
    grid-area: sub;
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    font-size: var(--ds-text-sm);
    color: var(--ds-color-text-muted);
  }
  .sky-ov-pipe__sub[data-size='long'] {
    display: none;
  }

  @media (min-width: 48rem) {
    .sky-ov-pipe {
      gap: var(--ds-space-5);
    }
    .sky-ov-pipe__head h2 {
      font-size: var(--ds-text-xl);
    }
    .sky-ov-pipe__head p {
      display: block;
    }
    .sky-ov-pipe__list {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(min(13rem, 100%), 1fr));
      gap: var(--ds-space-3-5);
    }
    .sky-ov-pipe__item {
      flex-direction: column;
      align-items: stretch;
      gap: var(--ds-space-3-5);
      height: 100%;
      padding: var(--ds-space-5);
      border-radius: var(--sky-radius-xl);
      border: var(--ds-border-width) solid var(--ds-color-border);
      background: var(--ds-color-surface);
      box-shadow: var(--sky-shadow-raised);
    }
    .sky-ov-pipe__item:hover {
      border-color: var(--sky-color-border-hover);
      background: var(--ds-color-surface);
    }
    .sky-ov-pipe__icon {
      width: auto;
    }
    .sky-ov-pipe__icon :global(svg) {
      width: 4rem;
      height: 4rem;
    }
    .sky-ov-pipe__step {
      display: inline;
    }
    .sky-ov-pipe__text {
      display: flex;
      flex-direction: column;
      gap: var(--ds-space-0-5);
    }
    .sky-ov-pipe__count {
      font-size: var(--sky-text-figure);
      line-height: var(--ds-line-height-tight);
      letter-spacing: var(--sky-tracking-display);
    }
    .sky-ov-pipe__label {
      font-size: var(--sky-text-body);
    }
    .sky-ov-pipe__sub {
      white-space: normal;
    }
    .sky-ov-pipe__sub[data-size='long'] {
      display: block;
    }
    .sky-ov-pipe__sub[data-size='short'] {
      display: none;
    }
  }
</style>
