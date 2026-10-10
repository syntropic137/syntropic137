// PROBE: a path concatenated with a variable
import { request } from '../client'
export const x = (id: string) => request('/a/' + id)
