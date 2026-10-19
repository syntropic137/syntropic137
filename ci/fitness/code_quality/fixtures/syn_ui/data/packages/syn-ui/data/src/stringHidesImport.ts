// PROBE: a string hides import('svelte') from a comment stripper
const s = ' /* '; import('svelte'); const e = ' */ '
export { s, e }
