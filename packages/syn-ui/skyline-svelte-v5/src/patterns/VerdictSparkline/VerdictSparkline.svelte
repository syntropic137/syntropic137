<!--
  Verdict Sparkline (CompPatterns, Evals list): recent verdicts as small
  bars that read by height (pass 16, fail or error 8, unscored 3).
-->
<script lang="ts">
  import { VERDICT_BAR } from '@syn137/skyline-core/geometry'
  import { VERDICT_LOOK } from '@syn137/skyline-core/patterns'
  import type { VerdictSparklineProps } from './types'

  let { verdicts, ...rest }: VerdictSparklineProps = $props()

  const summary = $derived(
    verdicts.length === 0
      ? 'No runs'
      : verdicts.length === 1
        ? `Last run: ${VERDICT_LOOK[verdicts[0]!].label}`
        : `Last ${verdicts.length} runs: ${verdicts.map((v) => VERDICT_LOOK[v].label).join(', ')}`,
  )
</script>

<span {...rest} class="sky-sparkline" role="img" aria-label={summary}>
  {#each verdicts as v, i (i)}
    <span class="sky-sparkline__bar" data-verdict={v} style:height={`${VERDICT_BAR[v]}px`}></span>
  {/each}
</span>

<style>
  .sky-sparkline {
    display: inline-flex;
    align-items: flex-end;
    gap: 2px;
    height: 1rem;
  }
  .sky-sparkline__bar {
    width: 6px;
    border-radius: 1px;
    background: var(--ds-color-accent);
  }
  .sky-sparkline__bar[data-verdict='fail'] {
    background: var(--ds-color-danger);
  }
  .sky-sparkline__bar[data-verdict='error'] {
    background: var(--ds-color-warning);
  }
  .sky-sparkline__bar[data-verdict='unscored'] {
    background: var(--ds-color-text-subtle);
  }
</style>
