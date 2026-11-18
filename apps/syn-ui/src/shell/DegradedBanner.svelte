<!--
  Degraded mode (#693): a banner under the nav while GET /health says the
  instance is up but not fully serving, listing each reason as the API names
  it (the API sends no display labels, and the client does not invent them).
  A degraded answer with no reasons (startup gate holding, probe failed)
  still shows, with the API's status instead. Nothing renders when the
  instance is fully serving, or when the read itself fails: the live badge
  already covers an unreachable API.
-->
<script lang="ts">
  import { getHealth } from '@syn137/syn-ui-data'
  import { resource } from '../lib/load.svelte'

  // No activity event means "health changed"; `live` still refetches on
  // stream reconnect and on return to the tab, the moments it may have.
  const health = resource((signal) => getHealth(signal), { live: () => false })
  const degraded = $derived(health.error === undefined && health.data?.mode === 'degraded' ? health.data : undefined)
  const reasons = $derived(degraded?.degraded_reasons ?? [])
</script>

{#if degraded}
  <div class="sky-degraded" role="status" data-testid="degraded-banner">
    <strong class="sky-degraded__title">Degraded mode</strong>
    {#if reasons.length > 0}
      <ul class="sky-degraded__reasons">
        {#each reasons as reason (reason)}<li data-testid="degraded-reason">{reason}</li>{/each}
      </ul>
    {:else}
      <span class="sky-degraded__status">status: {degraded.status}</span>
    {/if}
  </div>
{/if}

<style>
  .sky-degraded {
    display: flex;
    flex-wrap: wrap;
    align-items: baseline;
    gap: var(--ds-space-2) var(--ds-space-3);
    box-sizing: border-box;
    /* The page column's content box: AppShell's crumbs and main pad it by the gutter. */
    width: calc(100% - 2 * var(--sky-gutter));
    max-width: calc(var(--sky-page-max) - 2 * var(--sky-gutter));
    margin: 0 auto var(--ds-space-3);
    padding: var(--ds-space-2) var(--ds-space-3);
    border-radius: var(--ds-radius-md);
    background: var(--sky-color-warning-soft);
    color: var(--sky-color-warning-soft-fg);
    font-size: var(--ds-text-sm);
  }
  .sky-degraded__reasons {
    display: flex;
    flex-wrap: wrap;
    gap: var(--ds-space-2);
    margin: 0;
    padding: 0;
    list-style: none;
  }
  .sky-degraded__reasons li,
  .sky-degraded__status {
    font-family: var(--ds-font-mono);
    font-size: var(--ds-text-xs);
  }
</style>
