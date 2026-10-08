<!-- Separator (SeparatorContract). CompDisplay "separator": a 1px hairline. -->
<script lang="ts">
  import type { SeparatorProps } from './types'

  let { orientation = 'horizontal', decorative = true, weight = 'border', ...rest }: SeparatorProps = $props()
</script>

<div
  {...rest}
  class="sky-separator"
  role={decorative ? 'none' : 'separator'}
  aria-orientation={!decorative && orientation === 'vertical' ? 'vertical' : undefined}
  data-orientation={orientation}
  data-weight={weight}
></div>

<style>
  .sky-separator {
    flex-shrink: 0;
    background: var(--ds-color-border);
  }
  .sky-separator[data-weight='divider'] {
    background: var(--sky-color-divider);
  }
  .sky-separator[data-orientation='horizontal'] {
    width: 100%;
    height: var(--ds-border-width);
  }
  .sky-separator[data-orientation='vertical'] {
    align-self: stretch;
    width: var(--ds-border-width);
    min-height: 1em;
  }
</style>
