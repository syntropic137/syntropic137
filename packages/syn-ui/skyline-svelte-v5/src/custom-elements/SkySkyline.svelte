<!--
  <sky-skyline>: Skyline with Day Readout as a custom element (options in
  ./options.ts). Set `days` (SkylineDay[]) as a JS property. `runs-href` is a
  URL template where {date} becomes the ISO day. Dispatches bubbling,
  composed events: `select` (detail: SkylineDay) and `yearchange` (detail:
  number). `selected` reflects the picked day to the attribute.
-->
<script lang="ts">
  import type { SkylineDay } from '@syn137/skyline-core/geometry'
  import Skyline from '../patterns/Skyline/Skyline.svelte'
  import type { SkylineProps } from '../patterns/Skyline/types'
  import { emit, hostAttachment } from './host'

  type Props = Partial<Pick<SkylineProps, 'days' | 'today' | 'year' | 'years' | 'wideFrom'>> & {
    selected?: string | null
    runsHref?: string
  }
  let { days = [], today, year, years, selected = $bindable(null), wideFrom, runsHref }: Props = $props()

  let host: HTMLElement | null = null
  const connect = hostAttachment(
    (h) => {
      host = h
    },
    { block: true },
  )

  const hrefFor = $derived.by(() => {
    const template = runsHref
    return template ? (d: SkylineDay) => template.replaceAll('{date}', encodeURIComponent(d.date)) : undefined
  })
  const onselect = (d: SkylineDay) => emit(host, 'select', d)
  const onyearchange = (y: number) => emit(host, 'yearchange', y)
</script>

<Skyline
  {days}
  {today}
  {year}
  {years}
  {wideFrom}
  bind:selected
  runsHref={hrefFor}
  {onselect}
  {onyearchange}
  {@attach connect}
/>
