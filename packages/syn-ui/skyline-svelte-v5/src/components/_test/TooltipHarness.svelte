<script lang="ts">
  import Tooltip from '../Tooltip/Tooltip.svelte'

  let { disabled = false }: { disabled?: boolean } = $props()
</script>

<Tooltip content="exec-66e14f235942" hint="Click to copy the full ID" openDelay={0} {disabled}>
  {#snippet trigger(props)}<button type="button" {...props}>66e14f23</button>{/snippet}
</Tooltip>
