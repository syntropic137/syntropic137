<!-- Empty State (CompDisplay "empty state"): a dashed frame, a title, one line and one action. -->
<script lang="ts">
  import type { EmptyStateProps } from './types'

  let { title, description, icon, action, level = 3, bare = false, children, ...rest }: EmptyStateProps = $props()
</script>

<div {...rest} class="sky-empty" data-bare={bare || undefined}>
  {#if icon}<span class="sky-empty__icon">{@render icon()}</span>{/if}
  <svelte:element this={`h${level}`} class="sky-empty__title">{title}</svelte:element>
  {#if description}<p class="sky-empty__description">{description}</p>{/if}
  {@render children?.()}
  {#if action}<div class="sky-empty__action">{@render action()}</div>{/if}
</div>

<style>
  .sky-empty {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: var(--ds-space-2-5);
    box-sizing: border-box;
    min-width: 0;
    padding: var(--ds-space-6) var(--ds-space-5);
    border: var(--ds-border-width) dashed var(--sky-color-border-strong);
    border-radius: var(--ds-space-4);
    text-align: center;
  }
  .sky-empty[data-bare] {
    border: 0;
  }
  .sky-empty__icon {
    display: flex;
    color: var(--ds-color-text-subtle);
  }
  .sky-empty__title {
    margin: 0;
    font-size: var(--sky-text-body);
    font-weight: var(--ds-font-weight-semibold);
    color: var(--ds-color-fg);
    overflow-wrap: anywhere;
  }
  .sky-empty__description {
    max-width: 36rem;
    margin: 0;
    font-size: var(--ds-text-sm);
    color: var(--ds-color-text-muted);
  }
  .sky-empty__action {
    display: flex;
    flex-wrap: wrap;
    justify-content: center;
    gap: var(--ds-space-2);
    margin-top: var(--ds-space-1);
  }
</style>
