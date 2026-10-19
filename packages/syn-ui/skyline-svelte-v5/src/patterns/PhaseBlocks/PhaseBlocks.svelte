<!--
  Phase Blocks (Execution board, Phase timeline): phases back to back as
  extruded blocks; length is time, height is tokens. Completed phases take
  the accent, a failed phase coral, a running one pulses, pending ones stay
  empty. Layout from layoutPhaseBlocks(); the SVG scales to its container.
-->
<script lang="ts">
  import { extrudeColors, layoutPhaseBlocks, type PhaseTone } from '@syn137/skyline-core/geometry'
  import type { PhaseBlocksProps } from './types'

  let { phases, label, ...rest }: PhaseBlocksProps = $props()

  const layout = $derived(layoutPhaseBlocks(phases))
  const BASE: Record<PhaseTone, string> = {
    done: 'var(--ds-color-accent)',
    running: 'var(--sky-color-running-block)',
    failed: 'var(--ds-color-danger)',
    cancelled: 'var(--ds-color-text-subtle)',
    pending: 'var(--sky-color-empty)',
  }
  const faces = $derived(Object.fromEntries(Object.entries(BASE).map(([k, v]) => [k, extrudeColors(v)])) as Record<PhaseTone, ReturnType<typeof extrudeColors>>)
  const summary = $derived(
    label ??
      `${phases.length} ${phases.length === 1 ? 'phase' : 'phases'} back to back. ` +
        phases.map((p) => `${p.name}${p.meta ? `: ${p.meta}` : ''}`).join('. '),
  )
</script>

<svg {...rest} class="sky-phase-blocks" viewBox={layout.viewBox} role="img" aria-label={summary}>
  {#each layout.blocks as b (b.index)}
    {@const f = faces[b.tone]}
    <g class="sky-phase-blocks__block" data-tone={b.tone}>
      <path d={b.paths.side} style:fill={f.side} />
      <path d={b.paths.front} style:fill={f.front} />
      <path d={b.paths.top} style:fill={f.top} />
    </g>
  {/each}
  {#each layout.blocks as b (b.index)}
    {#if b.number}<text class="sky-phase-blocks__number" data-tone={b.tone} x={b.number.x} y={b.number.y}>{b.number.text}</text>{/if}
    <text class="sky-phase-blocks__name" x={b.label.x} y={b.label.y}>{b.label.text}</text>
    {#if b.meta}<text class="sky-phase-blocks__meta" x={b.meta.x} y={b.meta.y}>{b.meta.text}</text>{/if}
  {/each}
</svg>

<style>
  .sky-phase-blocks {
    display: block;
    width: 100%;
    height: auto;
  }
  .sky-phase-blocks__number {
    font-family: var(--ds-font-mono);
    font-size: 12px;
    font-weight: var(--ds-font-weight-semibold);
    fill: var(--ds-color-accent-contrast);
  }
  .sky-phase-blocks__number:not([data-tone='done']) {
    fill: var(--ds-color-fg);
  }
  .sky-phase-blocks__name {
    font-family: var(--ds-font-sans);
    font-size: 13px;
    font-weight: var(--ds-font-weight-semibold);
    fill: var(--ds-color-fg);
  }
  .sky-phase-blocks__meta {
    font-family: var(--ds-font-mono);
    font-size: 11px;
    fill: var(--ds-color-text-muted);
  }
  @media (prefers-reduced-motion: no-preference) {
    .sky-phase-blocks__block[data-tone='running'] {
      animation: sky-phase-pulse 1.4s var(--sky-ease-in-out) infinite alternate;
    }
  }
  @keyframes sky-phase-pulse {
    to {
      opacity: 0.55;
    }
  }
</style>
