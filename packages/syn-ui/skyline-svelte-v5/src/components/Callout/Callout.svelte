<!-- Callout (CompDisplay): warning, error and note, each a glyph, a bold lead-in and the text. -->
<script lang="ts">
  import Glyph from '../_internal/Glyph.svelte'
  import type { CalloutProps } from './types'

  let { tone = 'note', title, icon, action, children, ...rest }: CalloutProps = $props()
</script>

<div {...rest} class="sky-callout" data-tone={tone}>
  <span class="sky-callout__icon">
    {#if icon}{@render icon()}{:else}<Glyph name={tone === 'note' ? 'info' : 'warning'} size={16} />{/if}
  </span>
  <div class="sky-callout__body">
    <p class="sky-callout__text">
      {#if title}<strong class="sky-callout__title">{title}</strong>{/if}
      {@render children?.()}
    </p>
    {#if action}<div class="sky-callout__action">{@render action()}</div>{/if}
  </div>
</div>

<style>
  .sky-callout {
    --_bg: var(--ds-color-surface-raised);
    --_fg: var(--sky-color-text-code);
    --_strong: var(--ds-color-fg);
    --_icon: var(--ds-color-accent);
    display: flex;
    align-items: flex-start;
    gap: var(--ds-space-3);
    box-sizing: border-box;
    min-width: 0;
    padding: var(--ds-space-3-5) var(--ds-space-4);
    border-radius: var(--sky-radius-row);
    background: var(--_bg);
    color: var(--_fg);
    font-size: var(--ds-text-sm);
    line-height: var(--ds-line-height-normal);
  }
  .sky-callout[data-tone='warning'] {
    --_bg: var(--sky-color-warning-soft);
    --_fg: var(--sky-color-warning-soft-fg);
    --_strong: color-mix(in oklab, var(--sky-color-warning-soft-fg) 60%, var(--ds-color-fg));
    --_icon: var(--ds-color-warning);
  }
  .sky-callout[data-tone='danger'] {
    --_bg: var(--sky-color-danger-soft);
    --_fg: color-mix(in oklab, var(--sky-color-danger-soft-fg) 65%, var(--ds-color-fg));
    --_strong: color-mix(in oklab, var(--sky-color-danger-soft-fg) 35%, var(--ds-color-fg));
    --_icon: var(--ds-color-danger);
  }
  .sky-callout__icon {
    display: flex;
    flex-shrink: 0;
    padding-top: 2px;
    color: var(--_icon);
  }
  .sky-callout__body {
    display: flex;
    flex: 1 1 auto;
    flex-wrap: wrap;
    align-items: center;
    justify-content: space-between;
    gap: var(--ds-space-2) var(--ds-space-4);
    min-width: 0;
  }
  .sky-callout__text {
    flex: 1 1 14rem;
    margin: 0;
    overflow-wrap: anywhere;
  }
  .sky-callout__title {
    font-weight: var(--ds-font-weight-semibold);
    color: var(--_strong);
  }
  .sky-callout__action {
    display: flex;
    gap: var(--ds-space-2);
  }
</style>
