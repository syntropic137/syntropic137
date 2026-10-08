<!-- Textarea (CompActions "label + textarea + hint"): the multi-line field. -->
<script lang="ts">
  import FieldMessage from './FieldMessage.svelte'
  import type { TextareaProps } from './types'

  let {
    value = $bindable(),
    size = 'md',
    invalid = false,
    message,
    messageTone,
    rows = 3,
    id,
    'aria-describedby': describedBy,
    ...rest
  }: TextareaProps = $props()

  const uid = $props.id()
  const fieldId = $derived(id ?? `${uid}-textarea`)
  const messageId = `${uid}-message`
  const tone = $derived(messageTone ?? (invalid ? 'danger' : 'neutral'))
  const isInvalid = $derived(invalid || tone === 'danger')
  const describedByAll = $derived([describedBy, message ? messageId : null].filter(Boolean).join(' ') || undefined)
</script>

<div class="sky-field">
  <textarea
    {...rest}
    bind:value
    class="sky-textarea"
    id={fieldId}
    {rows}
    data-size={size}
    data-invalid={isInvalid || undefined}
    aria-invalid={isInvalid || undefined}
    aria-describedby={describedByAll}
  ></textarea>
  {#if message}<FieldMessage id={messageId} {tone} text={message} />{/if}
</div>

<style>
  .sky-field {
    display: flex;
    flex-direction: column;
    gap: var(--ds-space-2);
    min-width: 0;
  }
  .sky-textarea {
    box-sizing: border-box;
    width: 100%;
    min-height: 5rem;
    padding: var(--ds-space-3) var(--ds-space-3-5);
    border: var(--ds-border-width) solid var(--sky-color-border-strong);
    border-radius: var(--sky-radius-control);
    background: var(--ds-color-bg);
    color: var(--ds-color-fg);
    font: inherit;
    font-size: 0.84375rem;
    line-height: var(--ds-line-height-normal);
    resize: vertical;
  }
  .sky-textarea::placeholder {
    color: var(--ds-color-text-subtle);
    opacity: 1;
  }
  .sky-textarea:hover:not(:disabled) {
    border-color: var(--sky-color-border-hover);
  }
  .sky-textarea[data-invalid] {
    border-color: var(--ds-color-danger);
  }
  .sky-textarea:disabled {
    opacity: 0.4;
  }
  .sky-textarea:focus-visible {
    outline: var(--sky-focus-ring-width) solid var(--sky-color-focus);
    outline-offset: var(--sky-focus-ring-offset);
  }
  @media (pointer: coarse) {
    .sky-textarea {
      font-size: 1rem;
    }
  }
</style>
