// PROBE: the route exists only in a test file (review 1)
import { request } from '../client'
export const x = () => request('/in-test-file')
