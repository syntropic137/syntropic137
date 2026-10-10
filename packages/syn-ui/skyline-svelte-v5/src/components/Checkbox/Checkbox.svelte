<!--
  Checkbox (CheckboxRootContract). CompActions: unchecked, checked, some
  rows (indeterminate), disabled. 18px box; 44px hit area on touch.
-->
<script lang="ts">
  import { untrack } from 'svelte'
  import Glyph from '../_internal/Glyph.svelte'
  import type { CheckboxProps } from './types'

  let {
    checked = $bindable(),
    defaultChecked = false,
    onCheckedChange,
    disabled = false,
    required = false,
    name,
    value,
    children,
    onchange,
    ...rest
  }: CheckboxProps = $props()

  let input: HTMLInputElement | undefined = $state()
  let internal = $state<boolean | 'indeterminate'>(untrack(() => defaultChecked))
  const current = $derived(checked ?? internal)
  const indeterminate = $derived(current === 'indeterminate')

  $effect(() => {
    if (input) input.indeterminate = indeterminate
  })

  function change(e: Event & { currentTarget: EventTarget & HTMLInputElement }) {
    onchange?.(e)
    const next = e.currentTarget.checked
    internal = next
    if (checked !== undefined) checked = next
    onCheckedChange?.(next)
    // Controlled callers may keep "indeterminate"; reflect what they hold.
    queueMicrotask(() => {
      if (input) {
        input.checked = current === true
        input.indeterminate = current === 'indeterminate'
      }
    })
  }
</script>

<label class="sky-checkbox" data-disabled={disabled || undefined} data-state={indeterminate ? 'indeterminate' : current ? 'checked' : 'unchecked'}>
  <span class="sky-checkbox__control">
    <input
      {...rest}
      bind:this={input}
      class="sky-checkbox__input"
      type="checkbox"
      checked={current === true}
      aria-checked={indeterminate ? 'mixed' : undefined}
      {disabled}
      {required}
      {name}
      {value}
      onchange={change}
    />
    <span class="sky-checkbox__box" aria-hidden="true">
      {#if indeterminate}
        <Glyph name="dash" size={12} strokeWidth={2.2} />
      {:else if current}
        <Glyph name="check" size={12} strokeWidth={2.2} />
      {/if}
    </span>
  </span>
  {#if children}<span class="sky-checkbox__label">{@render children()}</span>{/if}
</label>

<style>
  .sky-checkbox {
    display: inline-flex;
    align-items: center;
    gap: var(--ds-space-2-5);
    font-size: var(--ds-text-md);
    color: var(--ds-color-fg);
    cursor: pointer;
    -webkit-tap-highlight-color: transparent;
  }
  .sky-checkbox[data-disabled] {
    opacity: 0.4;
    cursor: not-allowed;
  }
  .sky-checkbox__control {
    position: relative;
    display: inline-flex;
    flex-shrink: 0;
  }
  .sky-checkbox__input {
    position: absolute;
    inset: 0;
    width: 100%;
    height: 100%;
    margin: 0;
    opacity: 0;
    cursor: inherit;
  }
  .sky-checkbox__box {
    display: flex;
    align-items: center;
    justify-content: center;
    box-sizing: border-box;
    width: 1.125rem;
    height: 1.125rem;
    border: 1.5px solid var(--sky-color-border-hover);
    border-radius: 5px;
    background: var(--ds-color-bg);
    color: var(--sky-color-accent-solid-contrast);
    pointer-events: none;
    transition:
      background-color var(--sky-duration-fast) var(--sky-ease-out),
      border-color var(--sky-duration-fast) var(--sky-ease-out);
  }
  .sky-checkbox:hover:not([data-disabled]) .sky-checkbox__box {
    border-color: var(--ds-color-accent);
  }
  .sky-checkbox[data-state='checked'] .sky-checkbox__box,
  .sky-checkbox[data-state='indeterminate'] .sky-checkbox__box {
    border-color: transparent;
    background: var(--ds-color-accent);
  }
  .sky-checkbox__input:focus-visible + .sky-checkbox__box {
    outline: var(--sky-focus-ring-width) solid var(--sky-color-focus);
    outline-offset: var(--sky-focus-ring-offset);
  }
  @media (pointer: coarse) {
    .sky-checkbox {
      min-height: var(--sky-size-touch);
    }
    .sky-checkbox__input {
      inset: 50% auto auto 50%;
      width: var(--sky-size-touch);
      height: var(--sky-size-touch);
      transform: translate(-50%, -50%);
    }
  }
</style>
