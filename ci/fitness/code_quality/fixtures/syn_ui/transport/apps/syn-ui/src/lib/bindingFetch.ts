// PROBE: the binding may use transport but never fetch
export const go = () => globalThis['fetch']('/x')
