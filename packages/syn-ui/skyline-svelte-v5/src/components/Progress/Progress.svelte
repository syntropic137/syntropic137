<!-- Progress (ProgressContract). CompDisplay "progress · phase 2 of 3": blocks filled in the accent. -->
<script lang="ts">
  import type { ProgressProps } from './types'

  let { value, max, tone = 'accent', segments, valueText, 'aria-label': ariaLabel, ...rest }: ProgressProps = $props()

  const count = $derived(Math.max(1, Math.floor(segments ?? 1)))
  const total = $derived(max ?? segments ?? 100)
  const indeterminate = $derived(value === null || value === undefined)
  /** Fill of each block, 0..1. */
  const fills = $derived.by(() => {
    if (indeterminate) return Array.from({ length: count }, () => 0)
    const progress = Math.min(1, Math.max(0, (value as number) / (total || 1))) * count
    return Array.from({ length: count }, (_, i) => Math.min(1, Math.max(0, progress - i)))
  })
</script>

<div
  {...rest}
  class="sky-progress"
  role="progressbar"
  aria-label={ariaLabel}
  aria-valuemin={0}
  aria-valuemax={indeterminate ? undefined : total}
  aria-valuenow={indeterminate ? undefined : (value as number)}
  aria-valuetext={valueText}
  data-tone={tone}
  data-state={indeterminate ? 'indeterminate' : (value as number) >= total ? 'complete' : 'loading'}
>
  {#each fills as fill, i (i)}
    <span class="sky-progress__block"><span class="sky-progress__fill" style:width={`${Math.round(fill * 10000) / 100}%`}></span></span>
  {/each}
</div>

<style>
  .sky-progress {
    --_fill: var(--ds-color-accent);
    display: flex;
    gap: 3px;
    height: 0.625rem;
    min-width: 0;
  }
  .sky-progress[data-tone='neutral'] {
    --_fill: var(--ds-color-text-subtle);
  }
  .sky-progress[data-tone='danger'] {
    --_fill: var(--ds-color-danger);
  }
  .sky-progress[data-tone='warning'] {
    --_fill: var(--ds-color-warning);
  }
  .sky-progress[data-tone='success'] {
    --_fill: var(--ds-color-success);
  }
  .sky-progress__block {
    position: relative;
    flex: 1 1 0;
    border-radius: 3px;
    background: var(--sky-color-empty);
    overflow: hidden;
  }
  .sky-progress__fill {
    display: block;
    height: 100%;
    background: var(--_fill);
    transition: width var(--sky-duration-slow) var(--sky-ease-out);
  }
  .sky-progress[data-state='indeterminate'] .sky-progress__block {
    background: var(--sky-color-running-block);
  }
  @media (prefers-reduced-motion: no-preference) {
    .sky-progress[data-state='indeterminate'] .sky-progress__block::after {
      content: '';
      position: absolute;
      inset: 0;
      background: linear-gradient(90deg, transparent, color-mix(in oklab, var(--_fill) 70%, transparent), transparent);
      transform: translateX(-100%);
      animation: sky-progress-sweep 1.4s var(--sky-ease-in-out) infinite;
    }
  }
  @keyframes sky-progress-sweep {
    to {
      transform: translateX(100%);
    }
  }
</style>
