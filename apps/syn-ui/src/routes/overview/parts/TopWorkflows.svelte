<!-- Most-run workflows: busiest first, bar width relative to the busiest. -->
<script lang="ts">
  import { formatInteger } from '@syn137/skyline-core/format'
  import type { TopWorkflow } from '@syn137/skyline-core/screens/overview'
  import { href } from '../../../lib/router'

  let { items, total }: { items: TopWorkflow[]; total: number } = $props()
</script>

<section class="sky-ov-card" aria-labelledby="sky-ov-top-title">
  <div class="sky-ov-card__head">
    <h2 id="sky-ov-top-title">Most-run workflows</h2>
    <a class="sky-ov-more" href={href('/workflows')}>All {formatInteger(total)} →</a>
  </div>
  {#if items.length === 0}
    <p class="sky-ov-top__empty">No workflow has run yet.</p>
  {:else}
    <ul class="sky-ov-top">
      {#each items as w (w.id)}
        <li>
          <a class="sky-ov-top__row" href={href(`/workflows/${encodeURIComponent(w.id)}`)}>
            <span class="sky-ov-top__line">
              <span class="sky-ov-top__name">{w.name}</span>
              <span class="sky-ov-mono">{w.runs}</span>
            </span>
            <span class="sky-ov-top__track"><span style:width="{w.percent}%"></span></span>
          </a>
        </li>
      {/each}
    </ul>
  {/if}
</section>

<style>
  .sky-ov-top {
    display: flex;
    flex-direction: column;
    gap: var(--ds-space-3);
    margin: 0;
    padding: 0;
    list-style: none;
  }
  .sky-ov-top__row {
    display: flex;
    flex-direction: column;
    gap: var(--ds-space-1-5);
    color: var(--ds-color-fg);
    text-decoration: none;
    border-radius: var(--ds-radius-sm);
  }
  .sky-ov-top__row:hover {
    color: var(--ds-color-fg);
  }
  .sky-ov-top__row:hover .sky-ov-top__track span {
    background: var(--ds-color-text-muted);
  }
  .sky-ov-top__row:focus-visible {
    outline: var(--sky-focus-ring-width) solid var(--sky-color-focus);
    outline-offset: var(--sky-focus-ring-offset);
  }
  @media (pointer: coarse) {
    .sky-ov-top__row {
      min-height: var(--sky-size-touch);
      justify-content: center;
    }
  }
  .sky-ov-top__line {
    display: flex;
    align-items: baseline;
    justify-content: space-between;
    gap: var(--ds-space-3);
    font-size: var(--ds-text-sm);
  }
  .sky-ov-top__name {
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .sky-ov-top__track {
    display: block;
    height: 6px;
    border-radius: 3px;
    background: var(--sky-color-track);
  }
  .sky-ov-top__track span {
    display: block;
    height: 6px;
    border-radius: 3px;
    background: var(--ds-color-text-subtle);
  }
  .sky-ov-top__empty {
    margin: 0;
    font-size: var(--ds-text-sm);
    color: var(--ds-color-text-muted);
  }
</style>
