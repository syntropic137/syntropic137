/**
 * Types of the <sky-*> landing elements, framework-neutral: the properties
 * each element takes, its events, and the tag map for
 * `document.querySelector('sky-s-mark')`. Pure types (no Svelte), so a React
 * or plain TypeScript app can use them; React JSX typings build on these in
 * `@syn137/skyline-svelte-v5/elements/react`.
 *
 * Arrays and objects are properties (React 19 sets them as properties on a
 * defined custom element); strings, numbers and booleans also work as
 * attributes, written in kebab case (`pass-at`, `max-sessions`, `cost-max`).
 */
import type {
  EvalExplorerProps,
  HarnessChipProps,
  HarnessLanesProps,
  HeroCityProps,
  SMarkProps,
  ToolLogProps,
  UsageBandProps,
} from '@syn137/skyline-core/patterns'

export type SkySMarkProperties = SMarkProps
export type SkyIsoCityProperties = HeroCityProps
export type SkyEvalExplorerProperties = EvalExplorerProps
export type SkyHarnessChipProperties = HarnessChipProps
export type SkyHarnessLanesProperties = HarnessLanesProps
export type SkyToolLogProperties = ToolLogProps
export interface SkyUsageBandProperties extends UsageBandProps {
  /** Extruded strip (default) or the landing's flat bar. */
  shape?: 'extruded' | 'flat'
  /** Counts and shares (default), swatches and names only, or none. */
  legend?: 'full' | 'compact' | 'none'
}

/** detail of <sky-eval-explorer>'s `verifierchange` event. */
export interface VerifierChangeDetail {
  /** Index into `verifiers`. */
  index: number
  name: string
}

export type SkySMarkElement = HTMLElement & Partial<SkySMarkProperties>
export type SkyIsoCityElement = HTMLElement & Partial<SkyIsoCityProperties>
export type SkyEvalExplorerElement = HTMLElement & Partial<SkyEvalExplorerProperties>
export type SkyHarnessChipElement = HTMLElement & Partial<SkyHarnessChipProperties>
export type SkyHarnessLanesElement = HTMLElement & Partial<SkyHarnessLanesProperties>
export type SkyToolLogElement = HTMLElement & Partial<SkyToolLogProperties>
export type SkyUsageBandElement = HTMLElement & Partial<SkyUsageBandProperties>

/** Tag name to properties, for typing wrappers in any framework. */
export interface SkyElementProperties {
  'sky-s-mark': SkySMarkProperties
  'sky-iso-city': SkyIsoCityProperties
  'sky-eval-explorer': SkyEvalExplorerProperties
  'sky-harness-chip': SkyHarnessChipProperties
  'sky-harness-lanes': SkyHarnessLanesProperties
  'sky-tool-log': SkyToolLogProperties
  'sky-usage-band': SkyUsageBandProperties
}

declare global {
  interface HTMLElementTagNameMap {
    'sky-s-mark': SkySMarkElement
    'sky-iso-city': SkyIsoCityElement
    'sky-eval-explorer': SkyEvalExplorerElement
    'sky-harness-chip': SkyHarnessChipElement
    'sky-harness-lanes': SkyHarnessLanesElement
    'sky-tool-log': SkyToolLogElement
    'sky-usage-band': SkyUsageBandElement
  }
  interface HTMLElementEventMap {
    verifierchange: CustomEvent<VerifierChangeDetail>
  }
}
