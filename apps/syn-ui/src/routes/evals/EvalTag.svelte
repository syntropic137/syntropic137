<!-- An eval tag chip: selects the tag filter, or clears it when removable. -->
<script lang="ts">
  import { Tag } from '@syn137/skyline-svelte-v5'

  let { tag, removable = false, onselect, onremove }: { tag: string; removable?: boolean; onselect?: () => void; onremove?: () => void } = $props()
</script>

<span class="sky-eval-tag">
  {#if removable}
    <Tag variant="outline" {onremove} removeLabel={`Clear tag filter ${tag}`} title={tag}>{tag}</Tag>
  {:else if onselect}
    <Tag variant="accent" onclick={onselect} title={`Filter by ${tag}`}>{tag}</Tag>
  {:else}
    <Tag variant="accent" title={tag}>{tag}</Tag>
  {/if}
</span>

<style>
  .sky-eval-tag {
    display: inline-flex;
    max-width: 100%;
    min-width: 0;
  }
  .sky-eval-tag :global(.sky-tag) {
    max-width: 100%;
  }
  .sky-eval-tag :global(.sky-tag__text) {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
</style>
