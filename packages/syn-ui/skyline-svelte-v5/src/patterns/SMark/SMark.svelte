<!--
  S Mark (Landing nav, hero and footer; the app's top bar later): the
  Syntropic137 S as eleven isometric cubes, from skyline-core's sMark().
  Faces are tokens (S_MARK_FACES), so the blue cubes follow the accent.
  `animate` drops the cubes in one by one with motion.css's sky-sdrop; the
  static mark is the end state (reduced motion, no motion.css, no script).
-->
<script lang="ts">
  import { sMark, sMarkDelay, S_MARK_FACES } from '@syn137/skyline-core/geometry'
  import type { SMarkProps } from './types'

  let { size, animate = false, label = 'Syntropic137', ...rest }: SMarkProps = $props()

  const mark = sMark(40)
  // A bare number, or a numeric string from an HTML attribute, is pixels.
  const width = $derived(typeof size === 'number' || (typeof size === 'string' && /^\d+(\.\d+)?$/.test(size)) ? `${size}px` : size)
</script>

<svg
  {...rest}
  class="sky-s-mark"
  viewBox={mark.viewBox}
  style:width
  role={label ? 'img' : undefined}
  aria-label={label || undefined}
  aria-hidden={label ? undefined : 'true'}
  focusable="false"
>
  {#each mark.cubes as c (c.order)}
    {@const f = S_MARK_FACES[c.tone]}
    <g class={animate ? 'sky-sdrop' : undefined} style:animation-delay={animate ? `${sMarkDelay(c.order)}s` : undefined} style:stroke={f.stroke}>
      <polygon points={c.left} style:fill={f.left} />
      <polygon points={c.right} style:fill={f.right} />
      <polygon points={c.top} style:fill={f.top} />
    </g>
  {/each}
</svg>

<style>
  .sky-s-mark {
    display: block;
    width: 100%;
    height: auto;
    overflow: visible;
  }
  .sky-s-mark g {
    stroke-width: 1;
    stroke-linejoin: round;
  }
</style>
