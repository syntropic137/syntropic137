<!--
  Text for screen readers only (icon-only buttons, chart summaries).
  Internal helper shared by components; also exported for app use.
-->
<script lang="ts">
  import type { Snippet } from 'svelte'
  import type { HTMLAttributes } from 'svelte/elements'

  let { children, ...rest }: HTMLAttributes<HTMLSpanElement> & { children: Snippet } = $props()
</script>

<span {...rest} class="sky-visually-hidden">{@render children()}</span>
