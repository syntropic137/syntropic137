<!--
  Tool Log Ticker (Landing pillar 03; the app's live execution view later):
  recent tool calls scrolling past in a box with soft top and bottom edges.
  The rows render twice and the track scrolls by one copy (motion.css
  sky-scroll), so a pass ends where it started.

  Energy (landing plan, section 7): the scroll plays only while the box is
  on screen (IntersectionObserver pauses it otherwise) and stops after
  about 20s of playing (tickerTiming). With reduced motion, `speed` 0 or no
  script, the rows stand still.
-->
<script lang="ts">
  import { tickerTiming, TOOL_LOG_SPEED } from '@syn137/skyline-core/patterns'
  import type { Attachment } from 'svelte/attachments'
  import type { ToolLogTickerProps } from './types'

  let { rows, speed = TOOL_LOG_SPEED, label = 'Recent tool calls', ...rest }: ToolLogTickerProps = $props()

  const timing = $derived(tickerTiming(rows.length, speed))
  let visible = $state(false)

  const watch: Attachment<HTMLElement> = (el) => {
    if (typeof IntersectionObserver === 'undefined') {
      visible = true
      return
    }
    const io = new IntersectionObserver((entries) => {
      for (const e of entries) visible = e.isIntersecting
    })
    io.observe(el)
    return () => io.disconnect()
  }
</script>

<div {...rest} class="sky-tool-log" role="group" aria-label={label} {@attach watch}>
  <div
    class={timing.moving ? 'sky-tool-log__track sky-scroll' : 'sky-tool-log__track'}
    style:animation-duration={timing.moving ? `${timing.duration}s` : undefined}
    style:animation-iteration-count={timing.moving ? timing.iterations : undefined}
    style:animation-play-state={timing.moving ? (visible ? 'running' : 'paused') : undefined}
  >
    {#each timing.moving ? [false, true] : [false] as copy (copy)}
      <ol class="sky-tool-log__rows" aria-hidden={copy ? 'true' : undefined}>
        {#each rows as r, i (i)}
          <li class="sky-tool-log__row">
            <span class="sky-tool-log__time">{r.time}</span>
            <span class="sky-tool-log__tool">{r.tool}</span>
            <span class="sky-tool-log__target">{r.target}</span>
            <span class="sky-tool-log__duration">{r.duration}</span>
          </li>
        {/each}
      </ol>
    {/each}
  </div>
</div>

<style>
  .sky-tool-log {
    position: relative;
    box-sizing: border-box;
    height: 11rem;
    overflow: hidden;
    border-radius: var(--sky-radius-row);
    border: var(--ds-border-width) solid var(--ds-color-border);
    background: var(--sky-color-ground-band);
    -webkit-mask-image: var(--sky-mask-fade-y);
    mask-image: var(--sky-mask-fade-y);
  }
  .sky-tool-log__track {
    display: flex;
    flex-direction: column;
  }
  .sky-tool-log__rows {
    display: flex;
    flex-direction: column;
    margin: 0;
    padding: 0;
    list-style: none;
  }
  .sky-tool-log__row {
    display: grid;
    grid-template-columns: 4rem 2.875rem minmax(0, 1fr) 3.25rem;
    gap: 10px;
    padding: 6px 10px;
    font-family: var(--ds-font-mono);
    font-size: var(--sky-text-data);
    line-height: var(--ds-line-height-normal);
    color: var(--ds-color-fg);
  }
  .sky-tool-log__time {
    color: var(--ds-color-text-subtle);
  }
  .sky-tool-log__tool {
    color: color-mix(in oklab, var(--ds-color-accent) 50%, var(--sky-color-display-hi));
  }
  .sky-tool-log__target {
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .sky-tool-log__duration {
    text-align: right;
    color: var(--ds-color-text-muted);
  }
</style>
