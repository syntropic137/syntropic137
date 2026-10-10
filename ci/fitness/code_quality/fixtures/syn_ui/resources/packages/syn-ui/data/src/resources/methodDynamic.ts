// PROBE: a method the check cannot read
import { request, type RequestOptions } from '../client'
export const x = (opts: RequestOptions) => request('/things', opts)
