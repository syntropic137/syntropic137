<!-- Scroll Area (ScrollAreaContract): content scrolls in its own box, never the page. -->
<script lang="ts">
  import type { ScrollAreaProps } from './types'
  import { SCROLL_AREA_ORIENTATION } from './variants'

  let { orientation = 'horizontal', maxHeight, hideScrollbar = false, 'aria-label': ariaLabel, children, ...rest }: ScrollAreaProps = $props()

  let el: HTMLDivElement | undefined = $state()
  let edges = $state({ start: false, end: false, top: false, bottom: false })
  const scrollable = $derived(edges.start || edges.end || edges.top || edges.bottom)

  function measure() {
    if (!el) return
    const { scrollLeft, scrollWidth, clientWidth, scrollTop, scrollHeight, clientHeight } = el
    const x = orientation !== 'vertical'
    const y = orientation !== 'horizontal'
    const next = {
      start: x && Math.abs(scrollLeft) > 1,
      end: x && Math.abs(scrollLeft) + clientWidth < scrollWidth - 1,
      top: y && scrollTop > 1,
      bottom: y && scrollTop + clientHeight < scrollHeight - 1,
    }
    if (next.start !== edges.start || next.end !== edges.end || next.top !== edges.top || next.bottom !== edges.bottom) edges = next
  }

  $effect(() => {
    if (!el) return
    measure()
    const ro = typeof ResizeObserver !== 'undefined' ? new ResizeObserver(measure) : null
    ro?.observe(el)
    for (const child of el.children) ro?.observe(child)
    return () => ro?.disconnect()
  })
</script>

<!-- svelte-ignore a11y_no_noninteractive_tabindex: a scrollable region must be keyboard reachable (WCAG 2.1.1). -->
<div
  {...rest}
  bind:this={el}
  class="sky-scroll-area"
  role={ariaLabel ? 'region' : undefined}
  aria-label={ariaLabel}
  tabindex={scrollable ? 0 : undefined}
  data-orientation={SCROLL_AREA_ORIENTATION[orientation]}
  data-hide-scrollbar={hideScrollbar || undefined}
  data-fade-start={edges.start || undefined}
  data-fade-end={edges.end || undefined}
  data-fade-top={edges.top || undefined}
  data-fade-bottom={edges.bottom || undefined}
  style:max-height={maxHeight}
  onscroll={measure}
>
  {@render children?.()}
</div>

<style>
  .sky-scroll-area {
    --_fade: var(--ds-space-6);
    min-width: 0;
    max-width: 100%;
    overscroll-behavior: contain;
    scrollbar-width: thin;
    scrollbar-color: var(--sky-color-border-strong) transparent;
    border-radius: var(--sky-radius-control);
  }
  .sky-scroll-area[data-orientation='horizontal'] {
    overflow-x: auto;
    overflow-y: hidden;
  }
  .sky-scroll-area[data-orientation='vertical'] {
    overflow-x: hidden;
    overflow-y: auto;
  }
  .sky-scroll-area[data-orientation='both'] {
    overflow: auto;
  }
  .sky-scroll-area[data-hide-scrollbar] {
    scrollbar-width: none;
  }
  .sky-scroll-area[data-hide-scrollbar]::-webkit-scrollbar {
    display: none;
  }
  /* Fades are masks: any opaque colour works, so the foreground token stands in. */
  .sky-scroll-area[data-fade-start] {
    mask-image: linear-gradient(90deg, transparent, var(--ds-color-fg) var(--_fade));
  }
  .sky-scroll-area[data-fade-end] {
    mask-image: linear-gradient(90deg, var(--ds-color-fg) calc(100% - var(--_fade)), transparent);
  }
  .sky-scroll-area[data-fade-start][data-fade-end] {
    mask-image: linear-gradient(90deg, transparent, var(--ds-color-fg) var(--_fade), var(--ds-color-fg) calc(100% - var(--_fade)), transparent);
  }
  .sky-scroll-area[data-fade-top] {
    mask-image: linear-gradient(180deg, transparent, var(--ds-color-fg) var(--_fade));
  }
  .sky-scroll-area[data-fade-bottom] {
    mask-image: linear-gradient(180deg, var(--ds-color-fg) calc(100% - var(--_fade)), transparent);
  }
  .sky-scroll-area[data-fade-top][data-fade-bottom] {
    mask-image: linear-gradient(180deg, transparent, var(--ds-color-fg) var(--_fade), var(--ds-color-fg) calc(100% - var(--_fade)), transparent);
  }
  .sky-scroll-area:focus-visible {
    outline: var(--sky-focus-ring-width) solid var(--sky-color-focus);
    outline-offset: var(--sky-focus-ring-offset);
  }
</style>
