/** Vite's `?raw` imports (tests read the API source they pin a contract to). */
declare module '*?raw' {
  const text: string
  export default text
}
