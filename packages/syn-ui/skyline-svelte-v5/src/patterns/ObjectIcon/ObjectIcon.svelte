<!--
  Object Icon (CompPatterns sheet): the three-face isometric object for a
  section (trigger, workflow, execution, session, artifact, eval). Shapes
  come from skyline-core's OBJECT_ICONS; faces resolve to the --sky-face-*
  tokens, so the icon recolours with the theme.
-->
<script lang="ts">
  import { OBJECT_ICONS, type IconFace } from '@syn137/skyline-core/geometry'
  import type { ObjectIconProps } from './types'

  let { kind, size = 64, label, ...rest }: ObjectIconProps = $props()

  const def = $derived(OBJECT_ICONS[kind])
  const FILL: Record<IconFace, string> = {
    top: 'var(--sky-face-top)',
    front: 'var(--sky-face-front)',
    side: 'var(--sky-face-side)',
    ink: 'var(--ds-color-bg)',
  }
</script>

<svg
  {...rest}
  class="sky-object-icon"
  data-kind={kind}
  width={size}
  height={size}
  viewBox="0 0 64 64"
  role={label ? 'img' : undefined}
  aria-label={label}
  aria-hidden={label ? undefined : 'true'}
  focusable="false"
>
  <ellipse class="sky-object-icon__glow" cx={def.glow.cx} cy={def.glow.cy} rx={def.glow.rx} ry={def.glow.ry} />
  {#each def.groups as group, g (g)}
    <g opacity={group.opacity}>
      {#each group.shapes as s, i (i)}
        {#if s.el === 'polygon'}
          <polygon points={s.points} style:fill={FILL[s.face]} opacity={s.opacity} />
        {:else if s.el === 'path'}
          <path d={s.d} style:fill={FILL[s.face]} opacity={s.opacity} />
        {:else}
          <path class="sky-object-icon__ink" d={s.d} stroke-width={s.width} opacity={s.opacity} />
        {/if}
      {/each}
    </g>
  {/each}
</svg>

<style>
  .sky-object-icon {
    display: block;
    flex-shrink: 0;
  }
  .sky-object-icon__glow {
    fill: var(--sky-face-front);
    opacity: 0.22;
  }
  .sky-object-icon__ink {
    fill: none;
    stroke: var(--ds-color-bg);
    stroke-linecap: round;
    stroke-linejoin: round;
  }
</style>
