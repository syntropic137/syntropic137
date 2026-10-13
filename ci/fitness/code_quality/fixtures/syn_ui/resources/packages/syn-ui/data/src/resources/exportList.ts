// PROBE: a local function exported by a list (review 1)
import { request } from '../client'
function x() {
  return request('/uncovered-list')
}
export { x }
