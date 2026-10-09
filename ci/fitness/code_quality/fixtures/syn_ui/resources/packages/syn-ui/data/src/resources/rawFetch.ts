// PROBE: a resource calling fetchJSON directly
import { fetchJSON } from '../client'
export const x = () => fetchJSON('/x')
