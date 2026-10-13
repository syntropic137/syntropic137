<!-- Label (LabelContract). "Task" on the left, "required · $ARGUMENTS" on the right. -->
<script lang="ts">
  import type { LabelProps } from './types'

  let { for: htmlFor, required = false, hint, children, ...rest }: LabelProps = $props()

  const note = $derived([required ? 'required' : null, hint].filter(Boolean).join(' · '))
</script>

<label {...rest} class="sky-label-field" for={htmlFor} data-required={required || undefined}>
  <span class="sky-label-field__text">{@render children?.()}</span>
  {#if note}<span class="sky-label-field__hint">{note}</span>{/if}
</label>

<style>
  .sky-label-field {
    display: flex;
    flex-wrap: wrap;
    align-items: baseline;
    justify-content: space-between;
    gap: var(--ds-space-1) var(--ds-space-3);
    font-size: var(--ds-text-sm);
    font-weight: var(--ds-font-weight-semibold);
    color: var(--ds-color-fg);
  }
  .sky-label-field__hint {
    font-family: var(--ds-font-mono);
    font-size: var(--ds-text-xs);
    font-weight: var(--ds-font-weight-regular);
    color: var(--ds-color-text-subtle);
  }
</style>
