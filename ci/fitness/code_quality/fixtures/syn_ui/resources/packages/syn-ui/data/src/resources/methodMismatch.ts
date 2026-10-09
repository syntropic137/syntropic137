// PROBE: no DELETE route for /things
import { request } from '../client'
export const x = () => request('/things', { method: 'DELETE' })
