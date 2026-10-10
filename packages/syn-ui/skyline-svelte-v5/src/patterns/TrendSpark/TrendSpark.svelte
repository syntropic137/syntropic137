<!--
  Trend Spark (Workflows board card): recent run durations as a line
  (higher is longer) beside a Faster / Slower / Steady word and its change.
  Text comes from skyline-core durationTrend(); this only renders it.
-->
<script lang="ts">
  import type { TrendSparkProps } from './types'

  let { kind, word, sub, label, spark, ...rest }: TrendSparkProps = $props()
</script>

<span {...rest} class="sky-trend-spark" data-kind={kind} role="img" aria-label={label}>
  <svg viewBox="0 0 200 40" preserveAspectRatio="none" aria-hidden="true">
    <path d={spark} vector-effect="non-scaling-stroke" />
  </svg>
  <span class="sky-trend-spark__text" aria-hidden="true">
    <span class="sky-trend-spark__word">{word}</span>
    <span class="sky-trend-spark__sub">{sub}</span>
  </span>
</span>

<style>
  .sky-trend-spark {
    display: flex;
    align-items: center;
    gap: var(--ds-space-2-5);
    flex-grow: 1;
    min-width: 0;
  }
  .sky-trend-spark svg {
    flex: 1 1 auto;
    min-width: 3rem;
    height: 1.625rem;
    overflow: visible;
  }
  .sky-trend-spark path {
    fill: none;
    stroke: var(--ds-color-accent);
    stroke-width: 2;
    stroke-linecap: round;
    stroke-linejoin: round;
  }
  .sky-trend-spark[data-kind='none'] path {
    stroke: var(--sky-color-border-strong);
  }
  .sky-trend-spark__text {
    display: flex;
    flex-direction: column;
    align-items: flex-end;
    gap: 1px;
    flex-shrink: 0;
  }
  .sky-trend-spark__word {
    font-size: var(--ds-text-xs);
    font-weight: var(--ds-font-weight-semibold);
    color: var(--ds-color-text-muted);
    white-space: nowrap;
  }
  .sky-trend-spark[data-kind='none'] .sky-trend-spark__word {
    color: var(--ds-color-text-subtle);
  }
  .sky-trend-spark[data-kind='faster'] .sky-trend-spark__word {
    color: var(--sky-color-success-soft-fg);
  }
  .sky-trend-spark[data-kind='slower'] .sky-trend-spark__word {
    color: var(--sky-color-danger-soft-fg);
  }
  .sky-trend-spark__sub {
    font-family: var(--ds-font-mono);
    font-size: var(--sky-text-label);
    color: var(--ds-color-text-subtle);
    white-space: nowrap;
  }
</style>
