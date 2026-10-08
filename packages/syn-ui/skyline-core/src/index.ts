/**
 * @syn137/skyline-core: plain TypeScript, no DOM, no Svelte.
 *
 * Prefer the subpath entries (`@syn137/skyline-core/format`, `/geometry`,
 * `/state`, `/patterns`, `/contracts`) in components; this barrel re-exports
 * them all for convenience. Everything is side-effect free and tree-shakes.
 */
export * from './format'
export * from './geometry'
export * from './state'
export * from './patterns'
export type * from './contracts'
