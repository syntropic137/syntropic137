// PROBE: routes outside the composed array serve nothing
import { request } from '../client'
export const x = () => request('/outside-array')
export const y = () => request('/never')
