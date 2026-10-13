<script lang="ts">
  import Popover from '../Popover/Popover.svelte'
  import Button from '../Button/Button.svelte'
  let { open = $bindable(false) }: { open?: boolean } = $props()
</script>

<button type="button">outside</button>
<Popover label="Filter by status" heading="Status" bind:open>
  {#snippet trigger(props)}<Button {...props}>Status</Button>{/snippet}
  {#snippet children({ close })}
    <button type="button">Completed</button>
    <button type="button" onclick={close}>Done</button>
  {/snippet}
</Popover>
