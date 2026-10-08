<script lang="ts">
  import Tooltip from '../Tooltip/Tooltip.svelte'
</script>

<Tooltip content="exec-66e14f235942" hint="Click to copy the full ID" delayDuration={0}>
  {#snippet trigger(props)}<button type="button" {...props}>66e14f23</button>{/snippet}
</Tooltip>
