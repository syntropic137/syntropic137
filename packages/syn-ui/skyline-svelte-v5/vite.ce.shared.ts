/**
 * The Svelte plugin both custom-element builds share (vite.ce.config.ts,
 * the all-in-one dist-ce bundle, and vite.elements.config.ts, the landing
 * elements). Only the wrappers in src/custom-elements/ compile as custom
 * elements; svelte.config.js (app, tests, svelte-check) is untouched.
 */
import { basename } from 'node:path'
import { svelte, vitePreprocess } from '@sveltejs/vite-plugin-svelte'
import type { PreprocessorGroup } from 'svelte/compiler'
import type { PluginOption } from 'vite'
import { CUSTOM_ELEMENT_OPTIONS } from './src/custom-elements/options'

const CE_WRAPPER = /[\\/]src[\\/]custom-elements[\\/][^\\/]+\.svelte$/

/** Object literal with bare keys: Svelte only reads `customElement` written that way. */
function literal(value: unknown): string {
  if (value && typeof value === 'object' && !Array.isArray(value)) {
    return `{ ${Object.entries(value).map(([k, v]) => `${k}: ${literal(v)}`).join(', ')} }`
  }
  return JSON.stringify(value)
}

/** Prepends <svelte:options customElement={...}> from options.ts to each wrapper. */
const customElementOptions: PreprocessorGroup = {
  name: 'skyline-custom-element-options',
  markup({ content, filename }) {
    if (!filename || !CE_WRAPPER.test(filename)) return
    const options = CUSTOM_ELEMENT_OPTIONS[basename(filename)]
    if (!options) throw new Error(`No custom-element options for ${filename} in src/custom-elements/options.ts`)
    return { code: `<svelte:options customElement={${literal(options)}} />${content}` }
  },
}

/** Svelte with component CSS injected at mount (into each element's shadow root). */
export function skylineCustomElements(): PluginOption {
  return svelte({
    configFile: false,
    preprocess: [customElementOptions, vitePreprocess()],
    emitCss: false,
    compilerOptions: { runes: true, css: 'injected' },
    dynamicCompileOptions: ({ filename }) => (CE_WRAPPER.test(filename) ? { customElement: true } : undefined),
  })
}
