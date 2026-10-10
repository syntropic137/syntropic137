<!--
  Phase Kit, compact (PhaseKit board, "Phase card footer"): model, tool
  count and skill count as small chips; absences as dashed chips.
-->
<script lang="ts">
  import { phaseKitChips } from '@syn137/skyline-core/patterns'
  import type { PhaseKitChipsProps } from './types'

  let { model, tools, skills, ...rest }: PhaseKitChipsProps = $props()
  const chips = $derived(phaseKitChips({ model, tools, skills }))
</script>

<span {...rest} class="sky-kit-chips">
  {#each chips as c (c.label)}
    <span class="sky-kit-chips__chip" data-tone={c.tone}>{c.label}</span>
  {/each}
</span>

<style>
  .sky-kit-chips {
    display: flex;
    flex-wrap: wrap;
    gap: var(--ds-space-1-5);
  }
  .sky-kit-chips__chip {
    height: 1.375rem;
    padding: 0 var(--ds-space-2);
    border-radius: 7px;
    background: var(--sky-color-control-hover);
    font-family: var(--ds-font-mono);
    font-size: var(--ds-text-xs);
    line-height: 1.375rem;
    color: var(--ds-color-text-muted);
    white-space: nowrap;
  }
  .sky-kit-chips__chip[data-tone='accent'] {
    background: var(--sky-color-accent-soft);
    color: var(--sky-color-accent-soft-fg);
  }
  .sky-kit-chips__chip[data-tone='dashed'] {
    height: 1.25rem;
    line-height: 1.125rem;
    background: transparent;
    border: var(--ds-border-width) dashed var(--sky-color-border-hover);
  }
</style>
