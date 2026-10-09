<!--
  Harness Lanes (Landing pillar 02; the Workflow detail header later): a
  workflow's phases in one lane per harness. Phase N sits in the same
  column in every lane; the harness that runs it fills the cell in its
  colour, the other lanes show an empty dashed slot. Widths follow `span`.
  Lane labels narrow from 120px to 86px in small containers.
-->
<script lang="ts">
  import { harnessLanes } from '@syn137/skyline-core/patterns'
  import type { HarnessLanesProps } from './types'

  let { phases, label = 'Phases by harness', ...rest }: HarnessLanesProps = $props()

  const lanes = $derived(harnessLanes(phases))
</script>

<div {...rest} class="sky-lanes" role="list" aria-label={label}>
  {#each lanes as lane (lane.label)}
    <div class="sky-lanes__lane" role="listitem" aria-label={lane.summary} style:--_lane={`var(${lane.token})`}>
      <span class="sky-lanes__name" aria-hidden="true"><span class="sky-lanes__dot"></span>{lane.label}</span>
      <span class="sky-lanes__cells" aria-hidden="true">
        {#each lane.cells as c (c.index)}
          <span class="sky-lanes__cell" data-on={c.on} style:flex-grow={c.span}>{c.name}</span>
        {/each}
      </span>
    </div>
  {/each}
</div>

<style>
  .sky-lanes {
    container-type: inline-size;
    display: flex;
    flex-direction: column;
    gap: var(--ds-space-4);
    min-width: 0;
  }
  .sky-lanes__lane {
    display: grid;
    grid-template-columns: 5.375rem minmax(0, 1fr);
    align-items: center;
    gap: var(--ds-space-3);
  }
  @container (min-width: 32rem) {
    .sky-lanes__lane {
      grid-template-columns: 7.5rem minmax(0, 1fr);
    }
    .sky-lanes__cell {
      padding: 0 var(--ds-space-3);
    }
  }
  .sky-lanes__name {
    display: flex;
    align-items: center;
    gap: var(--ds-space-2);
    min-width: 0;
    font-family: var(--ds-font-mono);
    font-size: var(--sky-text-data);
    color: var(--ds-color-text-muted);
  }
  .sky-lanes__dot {
    flex-shrink: 0;
    width: 9px;
    height: 9px;
    border-radius: 50%;
    background: var(--_lane);
  }
  .sky-lanes__cells {
    display: flex;
    gap: 6px;
    min-width: 0;
  }
  .sky-lanes__cell {
    flex: 1 1 0;
    display: flex;
    align-items: center;
    box-sizing: border-box;
    min-width: 0;
    height: 2.75rem;
    padding: 0 var(--ds-space-2);
    border-radius: var(--sky-radius-control);
    border: var(--ds-border-width) dashed var(--ds-color-border);
    font-size: var(--ds-text-sm);
    font-weight: var(--ds-font-weight-semibold);
    color: var(--ds-color-fg);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .sky-lanes__cell[data-on='true'] {
    border-style: solid;
    border-color: color-mix(in oklab, var(--_lane) 55%, var(--ds-color-border));
    background: color-mix(in oklab, var(--_lane) 22%, var(--ds-color-bg));
  }
</style>
