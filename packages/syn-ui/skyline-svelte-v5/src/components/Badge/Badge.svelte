<!--
  Badge (BadgeContract, required). CompDisplay board: Completed, Failed,
  Cancelled, Running and Pending pills, and the Pass / Fail / Error /
  Unscored verdicts. A status always pairs a glyph with the word, so it
  reads without colour.
-->
<script lang="ts">
  import type { BadgeProps } from './types'

  let { variant = 'soft', tone = 'neutral', size = 'md', icon, dot = false, children, ...rest }: BadgeProps = $props()
</script>

<span {...rest} class="sky-badge" data-variant={variant} data-tone={tone} data-size={size} data-has-icon={icon || dot ? '' : undefined}>
  {#if dot}
    <span class="sky-badge__dot" aria-hidden="true"></span>
  {:else if icon}
    <span class="sky-badge__icon">{@render icon()}</span>
  {/if}
  {#if children}<span class="sky-badge__label">{@render children()}</span>{/if}
</span>

<style>
  .sky-badge {
    --_bg: var(--sky-color-neutral-soft);
    --_fg: var(--ds-color-text-muted);
    --_border: transparent;

    display: inline-flex;
    align-items: center;
    gap: var(--ds-space-1-5);
    box-sizing: border-box;
    height: 1.625rem; /* 26 */
    max-width: 100%;
    padding: 0 var(--ds-space-3);
    border: var(--ds-border-width) solid var(--_border);
    border-radius: var(--ds-radius-full);
    background: var(--_bg);
    color: var(--_fg);
    font-size: var(--ds-text-sm);
    font-weight: var(--ds-font-weight-semibold);
    line-height: 1;
    white-space: nowrap;
    vertical-align: middle;
  }
  .sky-badge[data-has-icon] {
    padding-left: var(--ds-space-2-5);
  }
  .sky-badge[data-size='sm'] {
    height: 1.25rem; /* 20 */
    gap: var(--ds-space-1);
    padding: 0 var(--ds-space-2);
    font-size: var(--ds-text-xs);
  }
  .sky-badge__label {
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .sky-badge__icon {
    display: flex;
  }
  .sky-badge__icon :global(svg) {
    width: 0.75rem;
    height: 0.75rem;
  }
  .sky-badge__dot {
    flex-shrink: 0;
    width: 0.4375rem;
    height: 0.4375rem;
    border-radius: 50%;
    background: currentColor;
    box-shadow: 0 0 0 3px color-mix(in oklab, currentColor 24%, transparent);
  }
  @media (prefers-reduced-motion: no-preference) {
    .sky-badge__dot {
      animation: sky-badge-pulse 1.6s var(--sky-ease-in-out) infinite;
    }
  }
  @keyframes sky-badge-pulse {
    50% {
      box-shadow: 0 0 0 5px color-mix(in oklab, currentColor 10%, transparent);
    }
  }

  /* soft */
  .sky-badge[data-variant='soft'][data-tone='accent'] {
    --_bg: var(--sky-color-accent-soft);
    --_fg: var(--sky-color-accent-soft-fg);
  }
  .sky-badge[data-variant='soft'][data-tone='danger'] {
    --_bg: var(--sky-color-danger-soft);
    --_fg: var(--sky-color-danger-soft-fg);
  }
  .sky-badge[data-variant='soft'][data-tone='warning'] {
    --_bg: var(--sky-color-warning-soft);
    --_fg: var(--sky-color-warning-soft-fg);
  }
  .sky-badge[data-variant='soft'][data-tone='success'] {
    --_bg: color-mix(in oklab, var(--ds-color-success) 16%, transparent);
    --_fg: color-mix(in oklab, var(--ds-color-success) 55%, var(--ds-color-fg));
  }

  /* solid */
  .sky-badge[data-variant='solid'] {
    --_fg: var(--ds-color-bg);
  }
  .sky-badge[data-variant='solid'][data-tone='neutral'] {
    --_bg: var(--ds-color-text-muted);
  }
  .sky-badge[data-variant='solid'][data-tone='accent'] {
    --_bg: var(--sky-color-accent-solid);
    --_fg: var(--sky-color-accent-solid-contrast);
  }
  .sky-badge[data-variant='solid'][data-tone='danger'] {
    --_bg: var(--ds-color-danger);
  }
  .sky-badge[data-variant='solid'][data-tone='warning'] {
    --_bg: var(--ds-color-warning);
  }
  .sky-badge[data-variant='solid'][data-tone='success'] {
    --_bg: var(--ds-color-success);
  }

  /* outline: a quiet fill with a hairline (Cancelled reads as the canvas's grey pill) */
  .sky-badge[data-variant='outline'] {
    --_bg: var(--sky-color-neutral-soft);
    --_border: var(--sky-color-border-muted);
  }
  .sky-badge[data-variant='outline'][data-tone='accent'] {
    --_bg: transparent;
    --_fg: var(--sky-color-accent-soft-fg);
    --_border: var(--sky-color-accent-ring);
  }
  .sky-badge[data-variant='outline'][data-tone='danger'] {
    --_bg: transparent;
    --_fg: var(--sky-color-danger-soft-fg);
    --_border: color-mix(in oklab, var(--ds-color-danger) 35%, transparent);
  }
  .sky-badge[data-variant='outline'][data-tone='warning'] {
    --_bg: transparent;
    --_fg: var(--sky-color-warning-soft-fg);
    --_border: color-mix(in oklab, var(--ds-color-warning) 35%, transparent);
  }
  .sky-badge[data-variant='outline'][data-tone='success'] {
    --_bg: transparent;
    --_fg: var(--ds-color-success);
    --_border: color-mix(in oklab, var(--ds-color-success) 35%, transparent);
  }
</style>
