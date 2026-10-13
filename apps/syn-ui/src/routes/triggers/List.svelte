<!-- Triggers list. Boards: Triggers · PhoneTriggers. On a wide screen the first rule opens beside the list. -->
<script lang="ts">
  import type { PageProps } from '../../lib/routes'
  import TriggersScreen from './TriggersScreen.svelte'

  let { params: _params }: PageProps = $props()
</script>

<TriggersScreen selectedId={null} />
