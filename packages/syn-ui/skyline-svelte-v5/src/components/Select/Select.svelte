<!-- Select (SelectRootContract). CompActions "select": "Sort  Most run ▾" on the ground colour. -->
<script lang="ts">
  import { untrack } from 'svelte'
  import Glyph from '../_internal/Glyph.svelte'
  import type { SelectProps } from './types'
  import { SELECT_SIZE } from './variants'

  let {
    options,
    value = $bindable(),
    defaultValue,
    onValueChange,
    placeholder,
    size = 'md',
    disabled = false,
    name,
    label,
    invalid = false,
    id,
    onchange,
    ...rest
  }: SelectProps = $props()

  const uid = $props.id()
  const selectId = $derived(id ?? `${uid}-select`)
  let internal = $state(untrack(() => defaultValue ?? (placeholder ? '' : (options[0]?.value ?? ''))))
  const current = $derived(value ?? internal)

  function change(e: Event & { currentTarget: EventTarget & HTMLSelectElement }) {
    onchange?.(e)
    const next = e.currentTarget.value
    internal = next
    if (value !== undefined) value = next
    onValueChange?.(next)
  }
</script>

<span class="sky-select" data-size={SELECT_SIZE[size]} data-invalid={invalid || undefined} data-disabled={disabled || undefined}>
  {#if label}<label class="sky-select__prefix" for={selectId}>{label}</label>{/if}
  <select
    {...rest}
    class="sky-select__control"
    id={selectId}
    {name}
    {disabled}
    value={current}
    aria-invalid={invalid || undefined}
    onchange={change}
  >
    {#if placeholder}<option value="" disabled>{placeholder}</option>{/if}
    {#each options as o (o.value)}
      <option value={o.value} disabled={o.disabled}>{o.label}</option>
    {/each}
  </select>
  <span class="sky-select__chevron"><Glyph name="chevron-down" size={14} strokeWidth={1.75} /></span>
</span>

<style>
  .sky-select {
    position: relative;
    display: inline-flex;
    align-items: center;
    gap: var(--ds-space-2);
    box-sizing: border-box;
    height: 2.375rem;
    max-width: 100%;
    padding: 0 var(--ds-space-3);
    border: var(--ds-border-width) solid var(--sky-color-border-strong);
    border-radius: var(--sky-radius-control);
    background: var(--ds-color-bg);
    color: var(--ds-color-text-subtle);
    font-size: 0.84375rem;
  }
  .sky-select[data-size='sm'] {
    height: var(--sky-size-control-sm);
    border-radius: var(--ds-radius-md);
    font-size: var(--sky-text-data);
  }
  .sky-select[data-size='lg'] {
    height: var(--sky-size-control-lg);
    border-radius: var(--sky-radius-row);
    font-size: var(--sky-text-body);
  }
  .sky-select:hover:not([data-disabled]) {
    border-color: var(--sky-color-border-hover);
  }
  .sky-select[data-invalid] {
    border-color: var(--ds-color-danger);
  }
  .sky-select[data-disabled] {
    opacity: 0.4;
  }
  .sky-select:has(.sky-select__control:focus-visible) {
    outline: var(--sky-focus-ring-width) solid var(--sky-color-focus);
    outline-offset: var(--sky-focus-ring-offset);
  }
  .sky-select__prefix {
    flex-shrink: 0;
    cursor: pointer;
  }
  .sky-select__control {
    appearance: none;
    flex: 1 1 auto;
    min-width: 0;
    height: 100%;
    margin: 0;
    /* Room for the chevron, which sits over the control. */
    padding: 0 var(--ds-space-6) 0 0;
    border: 0;
    background: transparent;
    color: var(--ds-color-fg);
    font: inherit;
    text-overflow: ellipsis;
    cursor: pointer;
  }
  .sky-select__control:focus-visible {
    outline: none;
  }
  .sky-select__control option {
    background: var(--ds-color-surface-raised);
    color: var(--ds-color-fg);
  }
  .sky-select__chevron {
    position: absolute;
    right: var(--ds-space-3);
    display: flex;
    color: var(--ds-color-text-muted);
    pointer-events: none;
  }
  @media (pointer: coarse) {
    .sky-select {
      min-height: var(--sky-size-touch);
      font-size: 1rem;
    }
  }
</style>
