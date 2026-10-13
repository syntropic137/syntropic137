<!-- Skeleton (CompDisplay "skeleton"): a title bar and two lines, shimmering unless motion is reduced. -->
<script lang="ts">
  import type { SkeletonProps } from './types'

  let { variant = 'text', lines, width, height, label, ...rest }: SkeletonProps = $props()

  const WIDTHS = ['70%', '100%', '85%', '92%', '60%']
  const stack = $derived(
    lines && lines > 0 ? Array.from({ length: lines }, (_, i) => ({ variant: i === 0 ? 'title' : 'text', width: WIDTHS[i % WIDTHS.length]! })) : null,
  )
</script>

<div {...rest} class="sky-skeleton" role={label ? 'status' : undefined} aria-busy={label ? true : undefined} data-stack={stack ? '' : undefined}>
  {#if label}<span class="sky-visually-hidden">{label}</span>{/if}
  {#if stack}
    {#each stack as line, i (i)}
      <span class="sky-skeleton__bone" data-variant={line.variant} style:width={line.width} aria-hidden="true"></span>
    {/each}
  {:else}
    <span class="sky-skeleton__bone" data-variant={variant} style:width={width} style:height={height} aria-hidden="true"></span>
  {/if}
</div>

<style>
  .sky-skeleton {
    display: flex;
    min-width: 0;
  }
  .sky-skeleton[data-stack] {
    flex-direction: column;
    gap: var(--ds-space-2);
  }
  .sky-skeleton__bone {
    position: relative;
    display: block;
    width: 100%;
    height: 0.625rem;
    border-radius: 5px;
    background: var(--sky-color-track);
    overflow: hidden;
  }
  .sky-skeleton__bone[data-variant='title'] {
    height: 0.875rem;
    border-radius: 7px;
    background: var(--sky-color-control-hover);
  }
  .sky-skeleton__bone[data-variant='block'] {
    height: 6rem;
    border-radius: var(--sky-radius-row);
  }
  .sky-skeleton__bone[data-variant='circle'] {
    width: 2rem;
    height: 2rem;
    border-radius: 50%;
  }
  @media (prefers-reduced-motion: no-preference) {
    .sky-skeleton__bone::after {
      content: '';
      position: absolute;
      inset: 0;
      background: linear-gradient(90deg, transparent, var(--sky-color-highlight-strong), transparent);
      transform: translateX(-100%);
      animation: sky-skeleton-shimmer 1.6s var(--sky-ease-in-out) infinite;
    }
  }
  @keyframes sky-skeleton-shimmer {
    to {
      transform: translateX(100%);
    }
  }
</style>
