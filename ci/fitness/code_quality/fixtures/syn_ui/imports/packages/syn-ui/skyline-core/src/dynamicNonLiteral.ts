// PROBE: dynamic import of a non-literal cannot be checked
export const live = (name: string) => import(name)
