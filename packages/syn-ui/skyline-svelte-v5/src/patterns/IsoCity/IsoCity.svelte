<!--
  Iso City (Landing hero; an optional Overview header later): one
  isometric block per day of agent runs, taller for busier days, from
  skyline-core's isoCity(). Live days pulse, failed days flash, errored
  days are amber.

  Motion is opt-in and finite (landing plan, section 7): `animate` raises
  the blocks back to front (sky-rise) and lets live and failed blocks
  pulse or flash a few times; `drift` drifts and zooms the stage once
  (sky-drift, 30s). The static city is the end state.

  `fill` picks how a quiet day shows: glass (default, the board) fades the
  whole block; solid keeps the faces opaque and darkens them instead.
-->
<script lang="ts">
  import { CITY_SIGNAL_DELAY, cityBlockPaint, cityDelay, isoCity, type CityBlock } from '@syn137/skyline-core/geometry'
  import type { IsoCityProps } from './types'

  let {
    days,
    live = [],
    failed = [],
    errored = [],
    animate = false,
    drift = false,
    fill = 'glass',
    cols = 26,
    rows = 11,
    cell = 36,
    maxSessions,
    label = 'A city of blocks, one per day of agent runs',
    overlay,
    ...rest
  }: IsoCityProps = $props()

  const uid = $props.id()
  const city = $derived(isoCity(days, { cols, rows, cell, live, failed, errored, maxSessions }))
  const paint = (b: CityBlock) => cityBlockPaint(b.tone, b.opacity, fill)

  function motion(b: CityBlock): { cls: string | undefined; delay: string | undefined } {
    if (!animate) return { cls: undefined, delay: undefined }
    const d = cityDelay(b.wave)
    const signal = b.tone === 'live' ? ' sky-pulse' : b.tone === 'failed' ? ' sky-flash' : ''
    // As on the board: a live pulse or failed flash starts 1.6s after the block's rise.
    return { cls: `sky-rise${signal}`, delay: signal ? `${d}s, ${Math.round((d + CITY_SIGNAL_DELAY) * 100) / 100}s` : `${d}s` }
  }
</script>

<div {...rest} class="sky-iso-city">
  <div class={drift ? 'sky-iso-city__stage sky-drift' : 'sky-iso-city__stage'}>
    <svg class="sky-iso-city__svg" viewBox={city.viewBox} role="img" aria-label={label}>
      <defs>
        <radialGradient id="{uid}-glow" cx="55%" cy="55%" r="55%">
          <stop class="sky-iso-city__glow-in" offset="0" />
          <stop class="sky-iso-city__glow-out" offset="1" />
        </radialGradient>
      </defs>
      <ellipse cx={city.glow.cx} cy={city.glow.cy} rx={city.glow.rx} ry={city.glow.ry} fill="url(#{uid}-glow)" />
      <polygon class="sky-iso-city__floor" points={city.floor} />
      {#each city.blocks as b (b.index)}
        {@const f = paint(b)}
        {@const m = motion(b)}
        <g class={m.cls} style:animation-delay={m.delay} style:opacity={f.opacity === 1 ? undefined : f.opacity} data-tone={b.tone}>
          <polygon points={b.left} style:fill={f.front} />
          <polygon points={b.right} style:fill={f.side} />
          <polygon points={b.top} style:fill={f.top} />
        </g>
      {/each}
    </svg>
    {#if overlay}
      <div class="sky-iso-city__overlay">{@render overlay()}</div>
    {/if}
  </div>
</div>

<style>
  .sky-iso-city {
    position: relative;
    min-width: 0;
  }
  .sky-iso-city__stage {
    position: relative;
  }
  .sky-iso-city__svg {
    display: block;
    width: 100%;
    height: auto;
    overflow: visible;
  }
  .sky-iso-city__glow-in {
    stop-color: var(--ds-color-accent);
    stop-opacity: 0.35;
  }
  .sky-iso-city__glow-out {
    stop-color: var(--ds-color-accent);
    stop-opacity: 0;
  }
  .sky-iso-city__floor {
    fill: none;
    stroke: var(--ds-color-border);
    stroke-width: 1;
  }
  .sky-iso-city__overlay {
    position: absolute;
    inset: 0;
    display: flex;
    justify-content: center;
    align-items: flex-start;
    pointer-events: none;
    filter: drop-shadow(0 30px 40px color-mix(in oklab, var(--ds-color-accent) 45%, transparent));
  }
</style>
