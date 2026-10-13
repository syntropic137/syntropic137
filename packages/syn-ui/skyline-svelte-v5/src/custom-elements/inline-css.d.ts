// Vite's `?inline` CSS import (a string), used by host.ts in the custom-element build.
declare module '*.css?inline' {
  const css: string
  export default css
}
