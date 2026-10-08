<!--
  Input (CompActions "Input, Select, Label"): search with its glyph, a
  focused field, and the error state with its message.
-->
<script lang="ts">
  import Glyph from '../_internal/Glyph.svelte'
  import FieldMessage from './FieldMessage.svelte'
  import type { InputProps } from './types'

  let {
    value = $bindable(),
    type = 'text',
    size = 'md',
    invalid = false,
    message,
    messageTone,
    leading,
    trailing,
    id,
    'aria-describedby': describedBy,
    ...rest
  }: InputProps = $props()

  const uid = $props.id()
  const inputId = $derived(id ?? `${uid}-input`)
  const messageId = `${uid}-message`
  const tone = $derived(messageTone ?? (invalid ? 'danger' : 'neutral'))
  const isInvalid = $derived(invalid || tone === 'danger')
  const describedByAll = $derived([describedBy, message ? messageId : null].filter(Boolean).join(' ') || undefined)
</script>

<div class="sky-field">
  <div class="sky-input" data-size={size} data-invalid={isInvalid || undefined} data-disabled={rest.disabled || undefined}>
    {#if leading}
      <span class="sky-input__adornment">{@render leading()}</span>
    {:else if type === 'search'}
      <span class="sky-input__adornment"><Glyph name="search" size={14} /></span>
    {/if}
    <input
      {...rest}
      bind:value
      class="sky-input__control"
      id={inputId}
      {type}
      aria-invalid={isInvalid || undefined}
      aria-describedby={describedByAll}
    />
    {#if trailing}<span class="sky-input__adornment">{@render trailing()}</span>{/if}
  </div>
  {#if message}<FieldMessage id={messageId} tone={tone} text={message} />{/if}
</div>

<style>
  .sky-field {
    display: flex;
    flex-direction: column;
    gap: var(--ds-space-1-5);
    min-width: 0;
  }
  .sky-input {
    display: flex;
    align-items: center;
    gap: var(--ds-space-2);
    box-sizing: border-box;
    height: 2.375rem; /* 38 */
    min-width: 0;
    padding: 0 var(--ds-space-3);
    border: var(--ds-border-width) solid var(--sky-color-border-strong);
    border-radius: var(--sky-radius-control);
    background: var(--ds-color-bg);
    color: var(--ds-color-text-subtle);
    font-size: 0.84375rem;
    transition: border-color var(--sky-duration-fast) var(--sky-ease-out);
  }
  .sky-input[data-size='sm'] {
    height: var(--sky-size-control-sm);
    border-radius: var(--ds-radius-md);
    font-size: var(--sky-text-data);
  }
  .sky-input[data-size='lg'] {
    height: var(--sky-size-control-lg);
    border-radius: var(--sky-radius-row);
    font-size: var(--sky-text-body);
  }
  .sky-input:hover:not([data-disabled]) {
    border-color: var(--sky-color-border-hover);
  }
  .sky-input[data-invalid] {
    border-color: var(--ds-color-danger);
  }
  .sky-input[data-disabled] {
    opacity: 0.4;
  }
  .sky-input:has(.sky-input__control:focus-visible) {
    outline: var(--sky-focus-ring-width) solid var(--sky-color-focus);
    outline-offset: var(--sky-focus-ring-offset);
  }
  .sky-input__adornment {
    display: flex;
    align-items: center;
    flex-shrink: 0;
    gap: var(--ds-space-1-5);
  }
  .sky-input__control {
    flex: 1 1 auto;
    min-width: 0;
    height: 100%;
    padding: 0;
    border: 0;
    background: transparent;
    color: var(--ds-color-fg);
    font: inherit;
    font-size: inherit;
  }
  .sky-input__control::placeholder {
    color: var(--ds-color-text-subtle);
    opacity: 1;
  }
  /* The ring is drawn on the field box above. */
  .sky-input__control:focus-visible {
    outline: none;
  }
  .sky-input__control::-webkit-search-cancel-button {
    filter: grayscale(1);
  }
  @media (pointer: coarse) {
    .sky-input {
      min-height: var(--sky-size-touch);
      /* 16px stops iOS zooming into the field. */
      font-size: 1rem;
    }
  }
</style>
