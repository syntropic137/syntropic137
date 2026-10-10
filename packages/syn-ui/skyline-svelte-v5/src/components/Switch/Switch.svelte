<!--
  Switch (SwitchRootContract). CompActions: on, off, focus, disabled.
  38 x 22 track; the hit area grows to 44px on touch pointers.
-->
<script lang="ts">
  import { untrack } from 'svelte'
  import type { SwitchProps } from './types'

  let {
    checked = $bindable(),
    defaultChecked = false,
    onCheckedChange,
    disabled = false,
    required = false,
    name,
    value = 'on',
    children,
    onclick,
    id,
    ...rest
  }: SwitchProps = $props()

  const uid = $props.id()
  const switchId = $derived(id ?? `${uid}-switch`)
  let internal = $state(untrack(() => defaultChecked))
  const on = $derived(checked ?? internal)

  function toggle(e: MouseEvent & { currentTarget: EventTarget & HTMLButtonElement }) {
    onclick?.(e)
    if (e.defaultPrevented) return
    const next = !on
    internal = next
    if (checked !== undefined) checked = next
    onCheckedChange?.(next)
  }
</script>

<span class="sky-switch-field" data-disabled={disabled || undefined}>
  <button
    {...rest}
    id={switchId}
    type="button"
    role="switch"
    class="sky-switch"
    aria-checked={on}
    aria-required={required || undefined}
    data-state={on ? 'checked' : 'unchecked'}
    {disabled}
    onclick={toggle}
  >
    <span class="sky-switch__knob" aria-hidden="true"></span>
  </button>
  {#if children}<label class="sky-switch-field__label" for={switchId}>{@render children()}</label>{/if}
  {#if name && on}<input type="hidden" {name} {value} />{/if}
</span>

<style>
  .sky-switch-field {
    display: inline-flex;
    align-items: center;
    gap: var(--ds-space-2-5);
    font-size: var(--ds-text-sm);
    color: var(--ds-color-fg);
  }
  .sky-switch-field[data-disabled] {
    opacity: 0.4;
  }
  .sky-switch-field__label {
    cursor: pointer;
  }
  .sky-switch {
    position: relative;
    display: inline-flex;
    align-items: center;
    flex-shrink: 0;
    box-sizing: border-box;
    width: 2.375rem; /* 38 */
    height: 1.375rem; /* 22 */
    padding: 2px;
    border: 0;
    border-radius: var(--ds-radius-full);
    background: var(--sky-color-border-muted);
    cursor: pointer;
    -webkit-tap-highlight-color: transparent;
    transition: background-color var(--sky-duration-base) var(--sky-ease-out);
  }
  .sky-switch[aria-checked='true'] {
    background: var(--sky-color-accent-solid);
  }
  .sky-switch:disabled {
    cursor: not-allowed;
  }
  .sky-switch__knob {
    width: 1.125rem;
    height: 1.125rem;
    border-radius: 50%;
    background: var(--ds-color-text-muted);
    box-shadow: var(--sky-shadow-knob);
    transition:
      transform var(--sky-duration-base) var(--sky-ease-out),
      background-color var(--sky-duration-base) var(--sky-ease-out);
  }
  .sky-switch[aria-checked='true'] .sky-switch__knob {
    transform: translateX(1rem);
    background: var(--sky-color-accent-solid-contrast);
  }
  .sky-switch:focus-visible {
    outline: var(--sky-focus-ring-width) solid var(--sky-color-focus);
    outline-offset: var(--sky-focus-ring-offset);
  }
  @media (pointer: coarse) {
    .sky-switch::after {
      content: '';
      position: absolute;
      inset: 50% auto auto 50%;
      width: var(--sky-size-touch);
      height: var(--sky-size-touch);
      transform: translate(-50%, -50%);
    }
    .sky-switch-field__label {
      padding: var(--ds-space-3) 0;
    }
  }
</style>
