<!--
  Verdict Block (CompPatterns, Evals board): one run's verdict as an
  isometric block. Height carries the verdict before colour does: tall
  pass, short fail or scorer error, flat unscored.
-->
<script lang="ts">
  import { VERDICT_BOX, verdictBlock } from '@syn137/skyline-core/geometry'
  import { VERDICT_FACES } from './faces'
  import type { VerdictBlockProps } from './types'

  let { verdict, size = 56, label, ...rest }: VerdictBlockProps = $props()

  const paths = $derived(verdictBlock(verdict))
  const f = $derived(VERDICT_FACES[verdict])
  const b = VERDICT_BOX
</script>

<svg
  {...rest}
  class="sky-verdict-block"
  data-verdict={verdict}
  width={size}
  height={(size * b.height) / b.width}
  viewBox={`0 0 ${b.width} ${b.height}`}
  role={label ? 'img' : undefined}
  aria-label={label}
  aria-hidden={label ? undefined : 'true'}
  focusable="false"
>
  <ellipse cx={b.glow.cx} cy={b.glow.cy} rx={b.glow.rx} ry={b.glow.ry} style:fill={f.front} opacity="0.2" />
  <path d={paths.front} style:fill={f.front} />
  <path d={paths.side} style:fill={f.side} />
  <path d={paths.top} style:fill={f.top} />
</svg>

<style>
  .sky-verdict-block {
    display: block;
    flex-shrink: 0;
  }
</style>
