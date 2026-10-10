/**
 * Custom-element options for each wrapper, keyed by file name.
 *
 * vite.ce.config.ts prepends `<svelte:options customElement={...} />` from
 * this table when it compiles a wrapper. The options are not written in the
 * .svelte files because the package's `check` (svelte-check with
 * --fail-on-warnings, no customElement compile option) reports every
 * `customElement` option as options_missing_custom_element, and that
 * warning cannot be silenced with svelte-ignore.
 *
 * Plain data only: this file is imported by the Vite config at build time.
 */
type PropType = 'String' | 'Boolean' | 'Number' | 'Array' | 'Object'
interface PropOption {
  type?: PropType
  attribute?: string
  reflect?: boolean
}
export interface CustomElementOptions {
  tag: `sky-${string}`
  shadow?: 'open' | 'none'
  props?: Record<string, PropOption>
}

export const CUSTOM_ELEMENT_OPTIONS: Record<string, CustomElementOptions> = {
  'SkyBadge.svelte': {
    tag: 'sky-badge',
    props: { variant: { type: 'String' }, tone: { type: 'String' }, size: { type: 'String' }, dot: { type: 'Boolean' } },
  },
  'SkyButton.svelte': {
    tag: 'sky-button',
    props: {
      variant: { type: 'String' },
      tone: { type: 'String' },
      size: { type: 'String' },
      type: { type: 'String' },
      href: { type: 'String' },
      label: { type: 'String' },
      disabled: { type: 'Boolean' },
      loading: { type: 'Boolean' },
      block: { type: 'Boolean' },
    },
  },
  'SkyCard.svelte': {
    tag: 'sky-card',
    props: {
      variant: { type: 'String' },
      padding: { type: 'String' },
      href: { type: 'String' },
      as: { type: 'String' },
      interactive: { type: 'Boolean' },
      selected: { type: 'Boolean' },
    },
  },
  'SkySkyline.svelte': {
    tag: 'sky-skyline',
    props: {
      days: { type: 'Array' },
      today: { type: 'String' },
      year: { type: 'Number' },
      years: { type: 'Array' },
      selected: { type: 'String', reflect: true },
      wideFrom: { type: 'Number', attribute: 'wide-from' },
      runsHref: { type: 'String', attribute: 'runs-href' },
    },
  },
  'SkyStat.svelte': {
    tag: 'sky-stat',
    props: { label: { type: 'String' }, value: { type: 'String' }, size: { type: 'String' } },
  },
  'SkyStatusBadge.svelte': {
    tag: 'sky-status-badge',
    props: { status: { type: 'String' }, shape: { type: 'String' }, label: { type: 'String' } },
  },
  'SkyTag.svelte': {
    tag: 'sky-tag',
    props: {
      variant: { type: 'String' },
      agent: { type: 'String' },
      href: { type: 'String' },
      removable: { type: 'Boolean' },
      removeLabel: { type: 'String', attribute: 'remove-label' },
    },
  },
  'SkyUsageMeter.svelte': {
    tag: 'sky-usage-meter',
    props: {
      cost: { type: 'String' },
      tokens: { type: 'Object' },
      costRows: { type: 'Array', attribute: 'cost-rows' },
      costBy: { type: 'String', attribute: 'cost-by' },
      note: { type: 'String' },
      rates: { type: 'Object' },
      heading: { type: 'String' },
    },
  },
}
