// PROBE: an exported arrow with an unindented local const before the request (review 2)
import { request } from '../client'
export const x = async () => {
const local = 1
  return request('/uncovered-after-local', { body: local })
}
