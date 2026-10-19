<!--
  Run Tiles (Execution board, CompPatterns): a phase's session ("Ran in")
  and its artifact ("Produced"), side by side; two stacked 44px tiles in a
  narrow container. A missing one reads "not recorded" in a dashed chip.
-->
<script lang="ts">
  import { GLYPH } from '@syn137/skyline-core/patterns'
  import Glyph from '../Glyph/Glyph.svelte'
  import type { RunTilesProps } from './types'

  let { phase, session, artifact, ...rest }: RunTilesProps = $props()
</script>

<div {...rest} class="sky-run-tiles">
  <div class="sky-run-tiles__inner">
    <div class="sky-run-tiles__pair">
      <span class="sky-run-tiles__label">Ran in</span>
      {#if session}
        <svelte:element
          this={session.href ? 'a' : 'span'}
          class="sky-run-tiles__tile"
          href={session.href}
          aria-label={session.href ? `Session ${session.id}${phase ? ` of ${phase}` : ''}` : undefined}
        >
          <span class="sky-run-tiles__icon"><Glyph d={GLYPH.terminal} /></span>
          <span class="sky-run-tiles__id">{session.id}</span>
          {#if session.note}<span class="sky-run-tiles__note">{session.note}</span>{/if}
        </svelte:element>
      {:else}
        <span class="sky-run-tiles__missing">not recorded</span>
      {/if}
    </div>
    <span class="sky-run-tiles__arrow" aria-hidden="true"><Glyph d={GLYPH.arrowRight} weight={1.5} /></span>
    <div class="sky-run-tiles__pair">
      <span class="sky-run-tiles__label">Produced</span>
      {#if artifact}
        <svelte:element
          this={artifact.href ? 'a' : 'span'}
          class="sky-run-tiles__tile"
          href={artifact.href}
          title={artifact.name}
          aria-label={artifact.href ? `Artifact${phase ? ` from ${phase}` : ''}, ${artifact.name}${artifact.size ? `, ${artifact.size}` : ''}` : undefined}
        >
          <span class="sky-run-tiles__icon"><Glyph d={GLYPH.file} weight={1.5} /></span>
          <span class="sky-run-tiles__id">{artifact.name}</span>
          {#if artifact.size}<span class="sky-run-tiles__size">{artifact.size}</span>{/if}
        </svelte:element>
      {:else}
        <span class="sky-run-tiles__missing">no artifact</span>
      {/if}
    </div>
  </div>
</div>

<style>
  .sky-run-tiles {
    container-type: inline-size;
    min-width: 0;
  }
  .sky-run-tiles__inner {
    display: flex;
    flex-direction: column;
    gap: var(--ds-space-2);
  }
  .sky-run-tiles__pair {
    display: flex;
    flex-direction: column;
    gap: var(--ds-space-1-5);
    min-width: 0;
  }
  .sky-run-tiles__label {
    font-family: var(--ds-font-mono);
    font-size: 0.625rem;
    letter-spacing: var(--sky-tracking-label);
    text-transform: uppercase;
    color: var(--ds-color-text-subtle);
  }
  .sky-run-tiles__arrow {
    display: none;
    color: var(--ds-color-text-subtle);
  }
  .sky-run-tiles__tile {
    display: flex;
    align-items: center;
    gap: 9px;
    min-width: 0;
    min-height: var(--sky-size-touch);
    padding: 0 var(--ds-space-3) 0 var(--ds-space-2-5);
    border-radius: var(--ds-radius-lg);
    border: var(--ds-border-width) solid var(--sky-color-border-strong);
    background: var(--ds-color-bg);
    color: var(--ds-color-fg);
    text-decoration: none;
  }
  a.sky-run-tiles__tile:hover {
    border-color: var(--sky-color-border-hover);
  }
  a.sky-run-tiles__tile:focus-visible {
    outline: var(--sky-focus-ring-width) solid var(--sky-color-focus);
    outline-offset: var(--sky-focus-ring-offset);
  }
  .sky-run-tiles__icon {
    display: inline-flex;
    flex-shrink: 0;
    color: var(--ds-color-accent);
  }
  .sky-run-tiles__id {
    min-width: 0;
    font-family: var(--ds-font-mono);
    font-size: 0.75rem;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .sky-run-tiles__note {
    min-width: 0;
    font-size: 0.75rem;
    color: var(--ds-color-text-muted);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .sky-run-tiles__size {
    flex-shrink: 0;
    font-family: var(--ds-font-mono);
    font-size: var(--ds-text-xs);
    color: var(--ds-color-text-muted);
  }
  .sky-run-tiles__missing {
    align-self: flex-start;
    height: 1.375rem;
    padding: 0 9px;
    border-radius: var(--ds-radius-md);
    border: var(--ds-border-width) dashed var(--sky-color-border-hover);
    font-family: var(--ds-font-mono);
    font-size: var(--ds-text-xs);
    line-height: 1.25rem;
    color: var(--ds-color-text-muted);
  }

  @container (min-width: 36rem) {
    .sky-run-tiles__inner {
      flex-direction: row;
      flex-wrap: wrap;
      align-items: center;
      gap: var(--ds-space-2) var(--ds-space-2-5);
    }
    .sky-run-tiles__pair {
      flex-direction: row;
      align-items: center;
      max-width: 100%;
      gap: var(--ds-space-2-5);
    }
    .sky-run-tiles__arrow {
      display: inline-flex;
    }
    .sky-run-tiles__tile {
      min-height: 2.125rem;
    }
    .sky-run-tiles__missing {
      align-self: center;
    }
  }
  @media (pointer: coarse) {
    .sky-run-tiles__tile {
      min-height: var(--sky-size-touch);
    }
  }
</style>
