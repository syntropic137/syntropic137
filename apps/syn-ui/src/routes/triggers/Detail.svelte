<!-- Trigger detail. Boards: Triggers · PhoneTriggers (the rule opens in place under its row on a phone). -->
<script lang="ts">
  import type { PageProps } from '../../lib/routes'
  import TriggersScreen from './TriggersScreen.svelte'

  let { params }: PageProps = $props()
</script>

<TriggersScreen selectedId={params.triggerId ?? null} />
