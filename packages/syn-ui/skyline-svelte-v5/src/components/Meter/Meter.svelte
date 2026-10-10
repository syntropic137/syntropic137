<!-- Meter (MeterContract). CompDisplay "meter": "Codex delegates to Claude · 26 runs" over its bar. -->
<script lang="ts">
  import type { MeterProps } from './types'
  import { METER_TONE } from './variants'

  let {
    value,
    min = 0,
    max = 1,
    low,
    high,
    optimum,
    tone,
    series,
    label,
    valueText,
    'aria-label': ariaLabel,
    ...rest
  }: MeterProps = $props()

  const uid = $props.id()
  const fraction = $derived(max > min ? Math.min(1, Math.max(0, (value - min) / (max - min))) : 0)

  type Region = 'low' | 'mid' | 'high'
  const regionOf = (v: number): Region => (low !== undefined && v < low ? 'low' : high !== undefined && v > high ? 'high' : 'mid')
  const resolvedTone = $derived.by(() => {
    if (tone) return tone
    if (optimum === undefined || (low === undefined && high === undefined)) return 'accent'
    return regionOf(value) === regionOf(optimum) ? 'accent' : 'warning'
  })
</script>

<div {...rest} class="sky-meter" data-tone={METER_TONE[resolvedTone]} data-series={series}>
  {#if label || valueText}
    <span class="sky-meter__head">
      {#if label}<span class="sky-meter__label" id={`${uid}-label`}>{label}</span>{/if}
      {#if valueText}<span class="sky-meter__value">{valueText}</span>{/if}
    </span>
  {/if}
  <span
    class="sky-meter__track"
    role="meter"
    aria-valuenow={value}
    aria-valuemin={min}
    aria-valuemax={max}
    aria-valuetext={valueText}
    aria-label={ariaLabel}
    aria-labelledby={!ariaLabel && label ? `${uid}-label` : undefined}
  >
    <span class="sky-meter__fill" style:width={`${fraction * 100}%`}></span>
  </span>
</div>

<style>
  .sky-meter {
    --_fill: var(--ds-color-accent);
    display: flex;
    flex-direction: column;
    gap: var(--ds-space-1-5);
    min-width: 0;
  }
  .sky-meter[data-tone='neutral'] {
    --_fill: var(--ds-color-text-subtle);
  }
  .sky-meter[data-tone='danger'] {
    --_fill: var(--ds-color-danger);
  }
  .sky-meter[data-tone='warning'] {
    --_fill: var(--ds-color-warning);
  }
  .sky-meter[data-tone='success'] {
    --_fill: var(--ds-color-success);
  }
  .sky-meter[data-series='data-1'] {
    --_fill: var(--sky-color-data-1);
  }
  .sky-meter[data-series='data-2'] {
    --_fill: var(--sky-color-data-2);
  }
  .sky-meter[data-series='data-3'] {
    --_fill: var(--sky-color-data-3);
  }
  .sky-meter[data-series='data-4'] {
    --_fill: var(--sky-color-data-4);
  }
  .sky-meter[data-series='claude'] {
    --_fill: var(--sky-color-agent-claude);
  }
  .sky-meter[data-series='codex'] {
    --_fill: var(--sky-color-agent-codex);
  }
  .sky-meter__head {
    display: flex;
    justify-content: space-between;
    gap: var(--ds-space-3);
    font-size: var(--ds-text-sm);
  }
  .sky-meter__label {
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .sky-meter__value {
    flex-shrink: 0;
    font-family: var(--ds-font-mono);
    font-variant-numeric: tabular-nums;
    color: var(--ds-color-text-muted);
  }
  .sky-meter__track {
    display: block;
    height: 0.375rem;
    border-radius: 3px;
    background: var(--sky-color-track);
    overflow: hidden;
  }
  .sky-meter__fill {
    display: block;
    height: 100%;
    border-radius: inherit;
    background: var(--_fill);
    transition: width var(--sky-duration-slow) var(--sky-ease-out);
  }
</style>
