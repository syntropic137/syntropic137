/**
 * @syn137/skyline-svelte-v5 custom-element entry (Platforms: non-Svelte hosts).
 *
 * Built only by `pnpm run build:ce` (vite.ce.config.ts) into
 * dist-ce/skyline-elements.js, a self-contained ES module with Svelte
 * bundled. Importing it registers the <sky-*> elements below. The host page
 * loads the theme itself (@syn137/skyline-themes/all.css) and sets
 * <html data-theme="skyline|syn137">; tokens inherit into each shadow root.
 *
 * The wrappers live in ./custom-elements/ and render the normal components
 * unchanged. Not part of the package's "." or "./patterns" exports, so the
 * Svelte app never pulls this file in.
 */
import SkyBadge from './custom-elements/SkyBadge.svelte'
import SkyButton from './custom-elements/SkyButton.svelte'
import SkyCard from './custom-elements/SkyCard.svelte'
import SkySkyline from './custom-elements/SkySkyline.svelte'
import SkyStat from './custom-elements/SkyStat.svelte'
import SkyStatusBadge from './custom-elements/SkyStatusBadge.svelte'
import SkyTag from './custom-elements/SkyTag.svelte'
import SkyUsageMeter from './custom-elements/SkyUsageMeter.svelte'

type ElementClass = CustomElementConstructor | undefined

/** Tag name to element class, in registration order. */
export const skylineElements: Record<string, ElementClass> = {
  'sky-badge': (SkyBadge as { element?: CustomElementConstructor }).element,
  'sky-button': (SkyButton as { element?: CustomElementConstructor }).element,
  'sky-card': (SkyCard as { element?: CustomElementConstructor }).element,
  'sky-skyline': (SkySkyline as { element?: CustomElementConstructor }).element,
  'sky-stat': (SkyStat as { element?: CustomElementConstructor }).element,
  'sky-status-badge': (SkyStatusBadge as { element?: CustomElementConstructor }).element,
  'sky-tag': (SkyTag as { element?: CustomElementConstructor }).element,
  'sky-usage-meter': (SkyUsageMeter as { element?: CustomElementConstructor }).element,
}

/**
 * Svelte registers each tag when its module loads (the `tag` option). This
 * guard is for hosts that load the bundle twice: it never redefines a tag.
 */
export function defineSkylineElements(registry: CustomElementRegistry = customElements): void {
  for (const [tag, ctor] of Object.entries(skylineElements)) {
    if (ctor && !registry.get(tag)) registry.define(tag, ctor)
  }
}
