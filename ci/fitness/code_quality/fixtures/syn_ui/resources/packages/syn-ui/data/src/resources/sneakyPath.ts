// PROBE: a path the check cannot read
import { request } from '../client'
export function x(path: string) {
  return request(path)
}
