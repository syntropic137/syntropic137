/**
 * The running build, for the shell: the API's release through the cached
 * getBuildInfo resource (one request, shared by every caller), folded with
 * this bundle's own version by skyline-core's buildView. Call during
 * component init (resource() uses $effect).
 */
import { getBuildInfo } from '@syn137/syn-ui-data'
import { buildView, type BuildView } from '@syn137/skyline-core/screens/version'
import { resource } from '../lib/load.svelte'

/** apps/syn-ui/package.json's version (lockstep with the product, bump_version.py), stamped by vite.config.ts. The served release still comes from the API. */
export const UI_VERSION: string = __SYN_UI_VERSION__

export function useBuild(): { readonly view: BuildView } {
  const info = resource((signal) => getBuildInfo(signal))
  const view = $derived(buildView(info.data, UI_VERSION))
  return {
    get view() {
      return view
    },
  }
}
