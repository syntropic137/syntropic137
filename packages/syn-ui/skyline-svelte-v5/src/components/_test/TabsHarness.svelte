<script lang="ts">
  import Tabs from '../Tabs/Tabs.svelte'
  let { activationMode = 'automatic', onValueChange }: { activationMode?: 'automatic' | 'manual'; onValueChange?: (v: string) => void } = $props()
</script>

<Tabs label="View" {activationMode} {onValueChange} items={[{ value: 'rendered', label: 'Rendered' }, { value: 'raw', label: 'Raw' }, { value: 'json', label: 'JSON', disabled: true }]}>
  {#snippet children(active)}Panel {active}{/snippet}
</Tabs>
