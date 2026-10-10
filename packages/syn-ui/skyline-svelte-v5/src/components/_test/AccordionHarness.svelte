<script lang="ts">
  import Accordion from '../Accordion/Accordion.svelte'
  let { type = 'single', collapsible = true }: { type?: 'single' | 'multiple'; collapsible?: boolean } = $props()
  const items = [
    { value: 'a', title: 'check_run.completed' },
    { value: 'b', title: 'pull_request.opened', disabled: true },
    { value: 'c', title: 'push' },
  ]
</script>

<Accordion {type} {collapsible} {items}>
  {#snippet children(item)}Rule for {item.title}{/snippet}
</Accordion>
