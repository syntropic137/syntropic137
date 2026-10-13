<!-- CLEAN: comments, other words and resource calls in markup -->
<script lang="ts">
  // fetch( in a comment
  import { listExecutions } from '@syn137/syn-ui-data'
  import { resource } from '../lib/load'
  const r = resource(() => listExecutions({}))
  function refetch(): void {}
</script>
<!-- fetch('/api/x') -->
<button onclick={() => refetch()} title="/apis are not /api paths">{String(r)}</button>
