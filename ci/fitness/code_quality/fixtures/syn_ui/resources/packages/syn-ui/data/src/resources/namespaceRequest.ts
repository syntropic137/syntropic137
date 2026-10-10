// PROBE: request through a namespace import
import * as client from '../client'
export function x() {
  return client.request('/uncovered-namespace')
}
