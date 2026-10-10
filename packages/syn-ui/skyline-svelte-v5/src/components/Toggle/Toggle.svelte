<!--
  Toggle (ToggleContract, required). CompActions board, "toggle off / on":
  a chip with aria-pressed. Skyline draws a pressed chip; on/off settings use
  Switch (spec: "Clarify Toggle").
-->
<script lang="ts">
  import { untrack } from 'svelte'
  import type { ToggleProps } from './types'
  import { TOGGLE_SIZE } from './variants'

  let {
    pressed = $bindable(),
    defaultPressed = false,
    onPressedChange,
    size = 'md',
    disabled = false,
    icon,
    children,
    onclick,
    ...rest
  }: ToggleProps = $props()

  let internal = $state(untrack(() => defaultPressed))
  const isPressed = $derived(pressed ?? internal)

  function toggle(e: MouseEvent & { currentTarget: EventTarget & HTMLButtonElement }) {
    onclick?.(e)
    if (e.defaultPrevented) return
    const next = !isPressed
    internal = next
    if (pressed !== undefined) pressed = next
    onPressedChange?.(next)
  }
</script>

<button
  {...rest}
  type="button"
  class="sky-toggle"
  {disabled}
  aria-pressed={isPressed}
  data-state={isPressed ? 'on' : 'off'}
  data-size={TOGGLE_SIZE[size]}
  data-icon-only={!children || undefined}
  onclick={toggle}
>
  {#if icon}<span class="sky-toggle__icon">{@render icon()}</span>{/if}
  {#if children}<span>{@render children()}</span>{/if}
</button>

<style>
  .sky-toggle {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    gap: var(--ds-space-2);
    box-sizing: border-box;
    height: var(--sky-size-nav-item);
    padding: 0 var(--ds-space-3-5);
    border: var(--ds-border-width) solid var(--sky-color-border-muted);
    border-radius: var(--ds-radius-lg);
    background: transparent;
    color: var(--ds-color-text-muted);
    font-family: inherit;
    font-size: var(--ds-text-sm);
    white-space: nowrap;
    cursor: pointer;
    -webkit-tap-highlight-color: transparent;
    transition:
      background-color var(--sky-duration-fast) var(--sky-ease-out),
      border-color var(--sky-duration-fast) var(--sky-ease-out),
      color var(--sky-duration-fast) var(--sky-ease-out);
  }
  .sky-toggle__icon {
    display: flex;
  }
  .sky-toggle[data-size='sm'] {
    height: 1.75rem;
    padding: 0 var(--ds-space-2-5);
    font-size: var(--sky-text-data);
  }
  .sky-toggle[data-size='lg'] {
    height: var(--sky-size-control-lg);
    padding: 0 var(--ds-space-4);
    font-size: var(--ds-text-md);
  }
  .sky-toggle[data-icon-only] {
    aspect-ratio: 1;
    padding: 0;
  }
  .sky-toggle:hover:not(:disabled) {
    border-color: var(--sky-color-border-hover);
    color: var(--ds-color-fg);
  }
  .sky-toggle[aria-pressed='true'] {
    border-color: var(--sky-color-border-hover);
    background: var(--ds-color-overlay);
    color: var(--ds-color-fg);
    box-shadow: var(--sky-shadow-selected);
  }
  .sky-toggle:focus-visible {
    outline: var(--sky-focus-ring-width) solid var(--sky-color-focus);
    outline-offset: var(--sky-focus-ring-offset);
  }
  .sky-toggle:disabled {
    opacity: 0.4;
    cursor: not-allowed;
  }
  @media (pointer: coarse) {
    .sky-toggle {
      min-height: var(--sky-size-touch);
    }
    .sky-toggle[data-icon-only] {
      min-width: var(--sky-size-touch);
    }
  }
</style>
