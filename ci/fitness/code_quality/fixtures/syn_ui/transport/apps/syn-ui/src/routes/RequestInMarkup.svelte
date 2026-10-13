<!-- PROBE: an aliased bridge called from markup -->
<script lang="ts">
  import { send } from '../lib/sendBridge'
</script>
<button onclick={() => send('/executions')}>go</button>
