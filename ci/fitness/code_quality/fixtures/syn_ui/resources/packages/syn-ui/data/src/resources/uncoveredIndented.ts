// PROBE: an indented exported function (review 2)
import { request } from '../client'
    export function x() {
      return request('/uncovered-indented')
    }
