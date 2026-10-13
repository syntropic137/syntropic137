/**
 * React 19 JSX typings for the <sky-*> landing elements. The package does
 * not depend on React: this file only augments the consumer's own `react`
 * types. Load it once in the React app, e.g. in src/sky-elements.d.ts:
 *
 *   import type {} from '@syn137/skyline-svelte-v5/elements/react'
 *
 * and import the elements you render (each registers its tag):
 *
 *   import '@syn137/skyline-svelte-v5/elements/s-mark'
 *   <sky-s-mark size={26} label="Syntropic137" />
 *   <sky-eval-explorer verifiers={sample} onverifierchange={(e) => setPick(e.detail.index)} />
 *
 * React 19 sets each prop as a property on a defined custom element, so
 * arrays and objects pass straight through. `on<event>` props listen for
 * that event name as written, so the explorer's event is `onverifierchange`.
 */
import type { DetailedHTMLProps, HTMLAttributes } from 'react'
import type { SkyElementProperties, VerifierChangeDetail } from '../src/elements/types'

type SkyJsx<P> = DetailedHTMLProps<HTMLAttributes<HTMLElement>, HTMLElement> & P & {
  /** Named slot of a light-DOM child (`<sky-s-mark slot="overlay">` inside `<sky-iso-city>`). */
  slot?: string
}

declare module 'react' {
  namespace JSX {
    interface IntrinsicElements {
      'sky-s-mark': SkyJsx<SkyElementProperties['sky-s-mark']>
      'sky-iso-city': SkyJsx<SkyElementProperties['sky-iso-city']>
      'sky-eval-explorer': SkyJsx<SkyElementProperties['sky-eval-explorer'] & { onverifierchange?: (event: CustomEvent<VerifierChangeDetail>) => void }>
      'sky-harness-chip': SkyJsx<SkyElementProperties['sky-harness-chip']>
      'sky-harness-lanes': SkyJsx<SkyElementProperties['sky-harness-lanes']>
      'sky-tool-log': SkyJsx<SkyElementProperties['sky-tool-log']>
      'sky-usage-band': SkyJsx<SkyElementProperties['sky-usage-band']>
    }
  }
}
