<script lang="ts">
  import DropdownMenu from '../DropdownMenu/DropdownMenu.svelte'
  import type { MenuEntry, MenuItem } from '../DropdownMenu/types'
  let { items, onSelect }: { items: MenuEntry[]; onSelect?: (item: MenuItem) => void } = $props()
</script>

<DropdownMenu {items} {onSelect} label="Sections">
  {#snippet trigger(props)}<button type="button" {...props}>More</button>{/snippet}
</DropdownMenu>
