<!--
  Button (ButtonContract, required). CompActions board: primary, secondary,
  ghost, danger and icon-only; hover, focus, pressed, disabled and busy;
  36px on desktop, 44px on touch pointers.

  Renders an <a> when `href` is set (and not disabled). `loading` keeps the
  button focusable but blocks activation and announces it as busy.
-->
<script lang="ts">
  import type { HTMLAnchorAttributes } from 'svelte/elements'
  import Spinner from './Spinner.svelte'
  import type { ButtonProps } from './types'

  let {
    variant = 'outline',
    tone,
    size = 'md',
    type = 'button',
    disabled = false,
    loading = false,
    href,
    block = false,
    icon,
    iconEnd,
    children,
    onclick,
    ...rest
  }: ButtonProps = $props()

  // Upstream variant names map onto Skyline's: primary = solid accent,
  // secondary = outline, danger = outline danger.
  const resolvedVariant = $derived(variant === 'primary' ? 'solid' : variant === 'secondary' || variant === 'danger' ? 'outline' : variant)
  const resolvedTone = $derived(tone ?? (variant === 'danger' ? 'danger' : resolvedVariant === 'solid' ? 'accent' : 'neutral'))
  const iconOnly = $derived(!children && !!(icon || loading))

  function handleClick(e: MouseEvent & { currentTarget: EventTarget & HTMLButtonElement }) {
    if (loading) {
      e.preventDefault()
      return
    }
    onclick?.(e)
  }
</script>

{#if href && !disabled}
  <a
    {...rest as HTMLAnchorAttributes}
    class="sky-button"
    {href}
    data-variant={resolvedVariant}
    data-tone={resolvedTone}
    data-size={size}
    data-icon-only={iconOnly || undefined}
    data-block={block || undefined}
    aria-busy={loading || undefined}
    aria-disabled={loading || undefined}
    onclick={(e) => {
      if (loading) e.preventDefault()
      else (onclick as ((e: MouseEvent) => void) | undefined)?.(e)
    }}
  >
    {#if loading}<Spinner />{:else if icon}<span class="sky-button__icon">{@render icon()}</span>{/if}
    {#if children}<span class="sky-button__label">{@render children()}</span>{/if}
    {#if iconEnd}<span class="sky-button__icon">{@render iconEnd()}</span>{/if}
  </a>
{:else}
  <button
    {...rest}
    class="sky-button"
    {type}
    {disabled}
    data-variant={resolvedVariant}
    data-tone={resolvedTone}
    data-size={size}
    data-icon-only={iconOnly || undefined}
    data-block={block || undefined}
    aria-busy={loading || undefined}
    aria-disabled={loading || undefined}
    onclick={handleClick}
  >
    {#if loading}<Spinner />{:else if icon}<span class="sky-button__icon">{@render icon()}</span>{/if}
    {#if children}<span class="sky-button__label">{@render children()}</span>{/if}
    {#if iconEnd}<span class="sky-button__icon">{@render iconEnd()}</span>{/if}
  </button>
{/if}

<style>
  .sky-button {
    --_bg: var(--sky-color-control);
    --_fg: var(--ds-color-fg);
    --_border: var(--sky-color-border-strong);
    --_shadow: var(--sky-shadow-raised);
    --_hover-bg: var(--sky-color-control-hover);
    --_hover-border: var(--sky-color-border-hover);
    --_h: var(--sky-size-control-md);

    display: inline-flex;
    align-items: center;
    justify-content: center;
    gap: var(--ds-space-2);
    box-sizing: border-box;
    height: var(--_h);
    min-width: 0;
    padding: 0 var(--ds-space-4);
    border: var(--ds-border-width) solid var(--_border);
    border-radius: var(--sky-radius-control);
    background: var(--_bg);
    box-shadow: var(--_shadow);
    color: var(--_fg);
    font-family: inherit;
    font-size: 0.84375rem; /* 13.5 */
    font-weight: var(--ds-font-weight-semibold);
    line-height: 1;
    text-decoration: none;
    white-space: nowrap;
    cursor: pointer;
    user-select: none;
    -webkit-tap-highlight-color: transparent;
    transition:
      background-color var(--sky-duration-fast) var(--sky-ease-out),
      border-color var(--sky-duration-fast) var(--sky-ease-out),
      filter var(--sky-duration-fast) var(--sky-ease-out);
  }
  .sky-button__label {
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .sky-button__icon {
    display: flex;
    flex-shrink: 0;
  }

  /* ---- Sizes ---- */
  .sky-button[data-size='sm'] {
    --_h: var(--sky-size-control-sm);
    padding: 0 var(--ds-space-3);
    border-radius: var(--ds-radius-md);
    font-size: var(--sky-text-data);
  }
  .sky-button[data-size='lg'] {
    --_h: var(--sky-size-control-lg);
    border-radius: var(--sky-radius-row);
    font-size: var(--sky-text-body);
  }
  .sky-button[data-icon-only] {
    width: var(--_h);
    padding: 0;
  }
  .sky-button[data-block] {
    display: flex;
    width: 100%;
  }

  /* ---- Variants x tones ---- */
  .sky-button[data-variant='solid'][data-tone='accent'] {
    --_bg: var(--sky-color-accent-solid);
    --_fg: var(--sky-color-accent-solid-contrast);
    --_border: transparent;
    --_shadow: var(--sky-shadow-glow);
    --_hover-bg: var(--sky-color-accent-solid);
    --_hover-border: transparent;
  }
  .sky-button[data-variant='solid'][data-tone='neutral'] {
    --_bg: var(--ds-color-fg);
    --_fg: var(--ds-color-bg);
    --_border: transparent;
    --_hover-bg: var(--ds-color-fg);
    --_hover-border: transparent;
  }
  .sky-button[data-variant='solid'][data-tone='danger'] {
    --_bg: var(--ds-color-danger);
    --_fg: var(--ds-color-bg);
    --_border: transparent;
    --_hover-bg: var(--ds-color-danger);
    --_hover-border: transparent;
  }
  .sky-button[data-variant='solid'][data-tone='warning'] {
    --_bg: var(--ds-color-warning);
    --_fg: var(--ds-color-bg);
    --_border: transparent;
    --_hover-bg: var(--ds-color-warning);
    --_hover-border: transparent;
  }
  .sky-button[data-variant='solid'][data-tone='success'] {
    --_bg: var(--ds-color-success);
    --_fg: var(--ds-color-bg);
    --_border: transparent;
    --_hover-bg: var(--ds-color-success);
    --_hover-border: transparent;
  }
  .sky-button[data-variant='solid']:hover:not(:disabled, [aria-disabled='true']) {
    filter: brightness(1.12);
  }

  .sky-button[data-variant='outline'][data-tone='accent'] {
    --_fg: var(--sky-color-accent-soft-fg);
    --_border: var(--sky-color-accent-ring);
    --_hover-border: var(--ds-color-accent);
  }
  .sky-button[data-variant='outline'][data-tone='danger'] {
    --_bg: var(--sky-color-danger-soft);
    --_fg: var(--sky-color-danger-soft-fg);
    --_border: color-mix(in oklab, var(--ds-color-danger) 28%, var(--ds-color-bg));
    --_shadow: none;
    --_hover-bg: color-mix(in oklab, var(--ds-color-danger) 16%, var(--sky-color-danger-soft));
    --_hover-border: color-mix(in oklab, var(--ds-color-danger) 50%, var(--ds-color-bg));
  }
  .sky-button[data-variant='outline'][data-tone='warning'] {
    --_bg: var(--sky-color-warning-soft);
    --_fg: var(--sky-color-warning-soft-fg);
    --_border: color-mix(in oklab, var(--ds-color-warning) 28%, var(--ds-color-bg));
    --_shadow: none;
    --_hover-border: color-mix(in oklab, var(--ds-color-warning) 50%, var(--ds-color-bg));
  }
  .sky-button[data-variant='outline'][data-tone='success'] {
    --_fg: var(--ds-color-success);
    --_border: color-mix(in oklab, var(--ds-color-success) 35%, var(--ds-color-bg));
  }

  .sky-button[data-variant='ghost'] {
    --_bg: transparent;
    --_fg: var(--ds-color-text-muted);
    --_border: transparent;
    --_shadow: none;
    --_hover-border: transparent;
  }
  .sky-button[data-variant='ghost'][data-tone='accent'] {
    --_fg: var(--ds-color-accent);
  }
  .sky-button[data-variant='ghost'][data-tone='danger'] {
    --_fg: var(--sky-color-danger-soft-fg);
    --_hover-bg: var(--sky-color-danger-soft);
  }
  .sky-button[data-variant='ghost'][data-tone='warning'] {
    --_fg: var(--sky-color-warning-soft-fg);
    --_hover-bg: var(--sky-color-warning-soft);
  }
  .sky-button[data-variant='ghost'][data-tone='success'] {
    --_fg: var(--ds-color-success);
  }
  .sky-button[data-variant='ghost']:hover:not(:disabled, [aria-disabled='true']) {
    color: var(--ds-color-fg);
  }

  /* ---- States ---- */
  .sky-button:hover:not(:disabled, [aria-disabled='true']) {
    background: var(--_hover-bg);
    border-color: var(--_hover-border);
  }
  .sky-button:active:not(:disabled, [aria-disabled='true']) {
    filter: brightness(0.88);
    box-shadow: none;
  }
  .sky-button:focus-visible {
    outline: var(--sky-focus-ring-width) solid var(--sky-color-focus);
    outline-offset: var(--sky-focus-ring-offset);
  }
  .sky-button:disabled {
    opacity: 0.4;
    cursor: not-allowed;
  }
  .sky-button[aria-busy='true'] {
    cursor: progress;
  }

  @media (pointer: coarse) {
    .sky-button {
      min-height: var(--sky-size-touch);
    }
    .sky-button[data-icon-only] {
      min-width: var(--sky-size-touch);
    }
  }
</style>
