<script lang="ts">
  import Dialog from '../Dialog/Dialog.svelte'
  let { onOpenChange }: { onOpenChange?: (open: boolean) => void } = $props()
</script>

<Dialog title="Transcript" titleId="2fd5ec12" {onOpenChange}>
  {#snippet trigger(props)}<button type="button" {...props}>View transcript</button>{/snippet}
  {#snippet children({ close })}<p>Body</p><button type="button" onclick={close}>Done</button>{/snippet}
</Dialog>
