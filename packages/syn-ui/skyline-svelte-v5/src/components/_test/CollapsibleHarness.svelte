<script lang="ts">
  import Collapsible from '../Collapsible/Collapsible.svelte'
  let { onOpenChange }: { onOpenChange?: (open: boolean) => void } = $props()
</script>

<Collapsible title="Outline" meta="2 sections" {onOpenChange}>Executive Summary</Collapsible>
