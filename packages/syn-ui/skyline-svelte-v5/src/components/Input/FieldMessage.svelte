<!-- The line under a field: "Must be at least 1." (danger) or the amber caution with its glyph. -->
<script lang="ts">
  import Glyph from '../_internal/Glyph.svelte'
  import type { FieldMessageTone } from './types'

  let { id, tone = 'neutral', text }: { id: string; tone?: FieldMessageTone; text: string } = $props()
</script>

<span class="sky-field-message" {id} data-tone={tone}>
  {#if tone === 'warning'}<span class="sky-field-message__icon"><Glyph name="warning" size={14} /></span>{/if}
  <span>{text}</span>
</span>

<style>
  .sky-field-message {
    display: flex;
    align-items: flex-start;
    gap: var(--ds-space-2);
    font-size: var(--sky-text-data);
    line-height: var(--ds-line-height-snug);
    color: var(--ds-color-text-muted);
  }
  .sky-field-message[data-tone='danger'] {
    color: var(--sky-color-danger-soft-fg);
  }
  .sky-field-message[data-tone='warning'] {
    color: var(--sky-color-warning-soft-fg);
  }
  .sky-field-message__icon {
    display: flex;
    padding-top: 1px;
    color: var(--ds-color-warning);
  }
</style>
