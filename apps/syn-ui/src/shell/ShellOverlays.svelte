<!-- Host for the shell overlays (lazy). Each overlay is mounted while open, so the palette reads the cache fresh each time and Dialog returns focus on close. -->
<script lang="ts">
  import CommandPalette from './CommandPalette.svelte'
  import ShortcutsDialog from './ShortcutsDialog.svelte'
  import { overlays } from './overlays.svelte'
</script>

{#if overlays.palette}<CommandPalette />{/if}
{#if overlays.shortcuts}<ShortcutsDialog />{/if}
