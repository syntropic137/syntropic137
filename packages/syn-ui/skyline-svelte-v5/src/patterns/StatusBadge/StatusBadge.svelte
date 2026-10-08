<!--
  Status Badge (CompDisplay, Main, Execution boards): a status read once
  through statusSemantics(), drawn as a pill, a square tile or a bare glyph.
  Screens pass the raw status and never pick colours.
-->
<script lang="ts">
  import { STATUS_GLYPH_PATHS, statusSemantics } from '@syn137/skyline-core/patterns'
  import Glyph from '../Glyph/Glyph.svelte'
  import type { StatusBadgeProps } from './types'

  let { status, shape = 'pill', label, ...rest }: StatusBadgeProps = $props()

  const s = $derived(statusSemantics(status))
  const text = $derived(label ?? s.label)
  const size = $derived(shape === 'pill' ? 12 : shape === 'square' ? 15 : 14)
</script>

<span
  {...rest}
  class="sky-status"
  data-shape={shape}
  data-variant={s.variant}
  data-tone={s.tone}
  data-kind={s.kind}
  data-live={s.live || undefined}
>
  <span class="sky-status__glyph"><Glyph d={STATUS_GLYPH_PATHS[s.glyph]} {size} weight={shape === 'pill' ? 2 : 1.9} /></span>
  {#if shape === 'pill'}
    <span class="sky-status__label">{text}</span>
  {:else}
    <span class="sky-visually-hidden">{text}</span>
  {/if}
</span>

<style>
  .sky-status {
    --_bg: var(--sky-color-neutral-soft);
    --_fg: var(--ds-color-text-muted);
    --_glyph: var(--ds-color-text-muted);
    display: inline-flex;
    align-items: center;
    justify-content: center;
    gap: var(--ds-space-1-5);
    flex-shrink: 0;
    color: var(--_glyph);
  }
  .sky-status[data-tone='accent'] {
    --_bg: var(--sky-color-accent-soft);
    --_fg: var(--sky-color-accent-soft-fg);
    --_glyph: var(--ds-color-accent);
  }
  .sky-status[data-tone='danger'] {
    --_bg: var(--sky-color-danger-soft);
    --_fg: var(--sky-color-danger-soft-fg);
    --_glyph: var(--ds-color-danger);
  }
  .sky-status[data-tone='warning'] {
    --_bg: var(--sky-color-warning-soft);
    --_fg: var(--sky-color-warning-soft-fg);
    --_glyph: var(--ds-color-warning);
  }

  .sky-status[data-shape='pill'] {
    height: 1.625rem;
    padding: 0 var(--ds-space-3) 0 var(--ds-space-2);
    border-radius: var(--ds-radius-full);
    background: var(--_bg);
    color: var(--_fg);
    font-size: var(--ds-text-sm);
    font-weight: var(--ds-font-weight-semibold);
    white-space: nowrap;
  }
  .sky-status[data-shape='pill'][data-variant='outline'] {
    background: transparent;
    box-shadow: inset 0 0 0 var(--ds-border-width) var(--sky-color-border-strong);
  }
  .sky-status[data-shape='pill'] .sky-status__glyph {
    color: currentColor;
  }

  .sky-status[data-shape='square'] {
    width: var(--sky-size-control-sm);
    height: var(--sky-size-control-sm);
    border-radius: var(--ds-radius-md);
    background: var(--_bg);
  }

  .sky-status__glyph {
    display: inline-flex;
  }

  @media (prefers-reduced-motion: no-preference) {
    .sky-status[data-live] .sky-status__glyph {
      animation: sky-status-spin 1.1s linear infinite;
    }
  }
  @keyframes sky-status-spin {
    to {
      transform: rotate(360deg);
    }
  }
</style>
