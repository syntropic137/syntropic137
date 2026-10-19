<!--
  Keycaps: a key combination drawn as separate caps (`⌃` `⇧` `F`), the shell's
  kbd style (TopNav's ⌘K hint). Screen readers get one name, "⌃+⇧+F".
-->
<script lang="ts">
  import type { KeycapsProps } from './types'

  let { keys, label, class: className, ...rest }: KeycapsProps = $props()
  const name = $derived(label ?? keys.join('+'))
</script>

<span {...rest} class={['sky-keycaps', className]} role="img" aria-label={name}>
  {#each keys as key, i (i)}<kbd class="sky-keycaps__key" aria-hidden="true">{key}</kbd>{/each}
</span>

<style>
  .sky-keycaps {
    display: inline-flex;
    align-items: center;
    gap: var(--ds-space-0-5);
    flex: none;
  }
  .sky-keycaps__key {
    min-width: 1.5em;
    padding: var(--ds-space-px) var(--ds-space-1-5);
    border-radius: var(--ds-radius-xs);
    border: var(--ds-border-width) solid var(--sky-color-border-strong);
    font-family: var(--ds-font-mono);
    font-size: var(--sky-text-label);
    line-height: 1.4;
    text-align: center;
    color: var(--ds-color-text-muted);
  }
</style>
