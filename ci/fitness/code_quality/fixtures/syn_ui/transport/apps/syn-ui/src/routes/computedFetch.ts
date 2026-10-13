// PROBE: computed member fetch and a concatenated /api/ path (review 1)
export const go = () => globalThis['fetch']('/api/' + 'v1/executions')
