<!--
  Pagination (PaginationContract). CompDisplay "pagination": the count, then
  Previous, "1 / 3", Next. On a phone the count takes its own line and the
  buttons reach 44px.
-->
<script lang="ts">
  import { clampPage, paginationRange } from '@syn137/skyline-core/state'
  import Button from '../Button/Button.svelte'
  import type { PaginationProps } from './types'

  let {
    page = $bindable(1),
    pageCount,
    onPageChange,
    siblingCount = 1,
    summary,
    mode = 'compact',
    previousLabel = 'Previous',
    nextLabel = 'Next',
    'aria-label': ariaLabel = 'Pagination',
    ...rest
  }: PaginationProps = $props()

  const count = $derived(Math.max(1, Math.floor(pageCount) || 1))
  const current = $derived(clampPage(page, count))
  const items = $derived(mode === 'pages' ? paginationRange(current, count, siblingCount) : [])

  function go(p: number) {
    const next = clampPage(p, count)
    if (next === current) return
    page = next
    onPageChange?.(next)
  }
</script>

<nav {...rest} class="sky-pagination" aria-label={ariaLabel} data-mode={mode}>
  {#if summary}<span class="sky-pagination__summary">{summary}</span>{/if}
  <div class="sky-pagination__controls">
    <Button size="sm" disabled={current <= 1} onclick={() => go(current - 1)}>{previousLabel}</Button>
    {#if mode === 'pages'}
      <ul class="sky-pagination__pages">
        {#each items as item, i (i)}
          <li>
            {#if item === 'gap'}
              <span class="sky-pagination__gap" aria-hidden="true">…</span>
            {:else}
              <button
                type="button"
                class="sky-pagination__page"
                aria-current={item === current ? 'page' : undefined}
                aria-label={`Page ${item}`}
                onclick={() => go(item)}>{item}</button
              >
            {/if}
          </li>
        {/each}
      </ul>
    {:else}
      <span class="sky-pagination__position" aria-live="polite">
        <span class="sky-visually-hidden">Page </span>{current}<span aria-hidden="true"> / </span><span class="sky-visually-hidden"> of </span>{count}
      </span>
    {/if}
    <Button size="sm" disabled={current >= count} onclick={() => go(current + 1)}>{nextLabel}</Button>
  </div>
</nav>

<style>
  .sky-pagination {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    justify-content: space-between;
    gap: var(--ds-space-3) var(--ds-space-4);
    font-size: var(--ds-text-sm);
    color: var(--ds-color-text-muted);
  }
  .sky-pagination__controls {
    display: flex;
    align-items: center;
    gap: var(--ds-space-3);
  }
  .sky-pagination__position {
    font-family: var(--ds-font-mono);
    font-size: var(--ds-text-sm);
    color: var(--ds-color-fg);
    font-variant-numeric: tabular-nums;
    white-space: nowrap;
  }
  .sky-pagination__pages {
    display: flex;
    gap: var(--ds-space-1);
    margin: 0;
    padding: 0;
    list-style: none;
  }
  .sky-pagination__page {
    min-width: var(--sky-size-control-sm);
    height: var(--sky-size-control-sm);
    padding: 0 var(--ds-space-2);
    border: var(--ds-border-width) solid transparent;
    border-radius: var(--ds-radius-md);
    background: transparent;
    color: var(--ds-color-text-muted);
    font-family: var(--ds-font-mono);
    font-size: var(--sky-text-data);
    cursor: pointer;
  }
  .sky-pagination__page:hover {
    color: var(--ds-color-fg);
    background: var(--sky-color-control-hover);
  }
  .sky-pagination__page[aria-current='page'] {
    border-color: var(--sky-color-border-hover);
    background: var(--ds-color-overlay);
    color: var(--ds-color-fg);
  }
  .sky-pagination__page:focus-visible {
    outline: var(--sky-focus-ring-width) solid var(--sky-color-focus);
    outline-offset: var(--sky-focus-ring-offset);
  }
  .sky-pagination__gap {
    display: inline-flex;
    align-items: center;
    height: var(--sky-size-control-sm);
    padding: 0 var(--ds-space-1);
  }
  @media (min-width: 48rem) {
    .sky-pagination {
      justify-content: flex-start;
    }
  }
  @media (pointer: coarse) {
    .sky-pagination__page {
      min-width: var(--sky-size-touch);
      min-height: var(--sky-size-touch);
    }
  }
</style>
