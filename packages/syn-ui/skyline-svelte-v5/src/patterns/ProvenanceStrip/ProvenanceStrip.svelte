<!--
  Provenance Strip (Execution board, CompPatterns): closes the phase list
  with session counts, the coverage warning, a note on what was not
  recorded, and revision and replication facts. The button goes full width
  in a narrow container.
-->
<script lang="ts">
  import { GLYPH, provenanceSummary } from '@syn137/skyline-core/patterns'
  import Glyph from '../Glyph/Glyph.svelte'
  import type { ProvenanceStripProps } from './types'

  let { title = 'Provenance', counts, warning, note, facts = [], actionLabel, onaction, busy = false, ...rest }: ProvenanceStripProps = $props()

  const summary = $derived(provenanceSummary(counts))
</script>

<section {...rest} class="sky-provenance" aria-label={rest['aria-label'] ?? title}>
  <div class="sky-provenance__inner">
    <div class="sky-provenance__head">
      <div class="sky-provenance__titles">
        <h3 class="sky-provenance__title">{title}</h3>
        {#if summary}<span class="sky-provenance__summary">{summary}</span>{/if}
      </div>
      {#if actionLabel}
        <button class="sky-provenance__action" type="button" onclick={onaction} disabled={busy} aria-busy={busy || undefined}>{actionLabel}</button>
      {/if}
    </div>
    {#if warning}
      <p class="sky-provenance__warning">
        <span class="sky-provenance__warning-icon"><Glyph d={GLYPH.warning} size={15} weight={1.5} /></span>
        <span><strong>{warning.lead}</strong>{#if warning.body}&nbsp;{warning.body}{/if}</span>
      </p>
    {/if}
    {#if note}<p class="sky-provenance__note">{note}</p>{/if}
    {#if facts.length}
      <ul class="sky-provenance__facts">
        {#each facts as f (f)}<li>{f}</li>{/each}
      </ul>
    {/if}
  </div>
</section>

<style>
  .sky-provenance {
    container-type: inline-size;
    min-width: 0;
  }
  .sky-provenance__inner {
    display: flex;
    flex-direction: column;
    gap: var(--ds-space-3);
  }
  .sky-provenance__head {
    display: flex;
    flex-direction: column;
    gap: var(--ds-space-2-5);
  }
  .sky-provenance__titles {
    display: flex;
    flex-wrap: wrap;
    align-items: baseline;
    gap: var(--ds-space-1-5) var(--ds-space-3);
  }
  .sky-provenance__title {
    margin: 0;
    font-size: var(--ds-text-md);
    font-weight: var(--ds-font-weight-semibold);
  }
  .sky-provenance__summary {
    font-family: var(--ds-font-mono);
    font-size: var(--ds-text-xs);
    color: var(--ds-color-text-muted);
  }
  .sky-provenance__action {
    height: var(--sky-size-touch);
    padding: 0 var(--ds-space-4);
    border-radius: var(--ds-radius-md);
    border: var(--ds-border-width) solid var(--sky-color-border-strong);
    background: var(--sky-color-control);
    box-shadow: var(--sky-shadow-raised);
    color: var(--ds-color-fg);
    font: inherit;
    font-size: var(--sky-text-data);
    font-weight: var(--ds-font-weight-semibold);
    cursor: pointer;
  }
  .sky-provenance__action:hover:not(:disabled) {
    background: var(--sky-color-control-hover);
  }
  .sky-provenance__action:disabled {
    color: var(--ds-color-text-subtle);
    cursor: progress;
  }
  .sky-provenance__action:focus-visible {
    outline: var(--sky-focus-ring-width) solid var(--sky-color-focus);
    outline-offset: var(--sky-focus-ring-offset);
  }
  .sky-provenance__warning {
    display: flex;
    align-items: flex-start;
    gap: var(--ds-space-2-5);
    margin: 0;
    font-size: var(--ds-text-sm);
    line-height: 1.5;
    color: var(--sky-color-warning-soft-fg);
  }
  .sky-provenance__warning strong {
    font-weight: var(--ds-font-weight-semibold);
    color: color-mix(in oklab, var(--sky-color-warning-soft-fg) 60%, var(--ds-color-fg));
  }
  .sky-provenance__warning-icon {
    display: inline-flex;
    margin-top: 2px;
    color: var(--ds-color-warning);
  }
  .sky-provenance__note {
    margin: 0;
    font-size: var(--sky-text-data);
    line-height: 1.5;
    color: var(--ds-color-text-muted);
  }
  .sky-provenance__facts {
    display: flex;
    flex-wrap: wrap;
    gap: var(--ds-space-1) var(--ds-space-4);
    margin: 0;
    padding: 0;
    list-style: none;
    font-family: var(--ds-font-mono);
    font-size: var(--ds-text-xs);
    color: var(--ds-color-text-subtle);
    overflow-wrap: anywhere;
  }
  @container (min-width: 32rem) {
    .sky-provenance__head {
      flex-direction: row;
      flex-wrap: wrap;
      align-items: center;
      justify-content: space-between;
      gap: var(--ds-space-2-5) var(--ds-space-4);
    }
    .sky-provenance__action {
      height: var(--sky-size-control-sm);
    }
  }
  @media (pointer: coarse) {
    .sky-provenance__action {
      min-height: var(--sky-size-touch);
    }
  }
</style>
