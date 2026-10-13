// PROBE: an exported arrow (review 1)
import { request } from '../client'
export const x = () => request('/uncovered-arrow')
