// PROBE: fetch aliased to a local (review 1)
const f = fetch
export const go = () => f('/x')
