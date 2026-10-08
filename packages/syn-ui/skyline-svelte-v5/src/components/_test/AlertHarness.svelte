<script lang="ts">
  import AlertDialog from '../AlertDialog/AlertDialog.svelte'
  let { onConfirm, onCancel }: { onConfirm?: () => void | Promise<unknown>; onCancel?: () => void } = $props()
</script>

<AlertDialog title="Delete this trigger?" description="Its firing log is kept." confirmLabel="Delete trigger" {onConfirm} {onCancel}>
  {#snippet trigger(props)}<button type="button" {...props}>Delete</button>{/snippet}
</AlertDialog>
