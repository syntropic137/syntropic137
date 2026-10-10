<!-- <sky-status-badge status="completed">: Status Badge pattern as a custom element (options in ./options.ts). -->
<script lang="ts">
  import StatusBadge from '../patterns/StatusBadge/StatusBadge.svelte'
  import type { StatusBadgeProps } from '../patterns/StatusBadge/types'
  import { hostAttachment } from './host'

  let { status, shape, label }: Partial<Pick<StatusBadgeProps, 'status' | 'shape' | 'label'>> = $props()

  const connect = hostAttachment()
</script>

<StatusBadge status={status ?? null} {shape} {label} {@attach connect} />
