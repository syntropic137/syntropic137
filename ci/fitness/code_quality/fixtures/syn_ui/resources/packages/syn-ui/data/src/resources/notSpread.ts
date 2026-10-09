// PROBE: the route module is imported, never spread (review 1)
import { request } from '../client'
export const x = () => request('/imported-not-spread')
