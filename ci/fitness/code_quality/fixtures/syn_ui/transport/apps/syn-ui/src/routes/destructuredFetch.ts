// PROBE: destructured fetch
const { fetch: f } = globalThis
export const go = () => f('/x')
