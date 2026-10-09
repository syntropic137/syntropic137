// PROBE: the whole concatenation is the path, not its first literal (review 1)
import { request } from '../client'
export const x = () => request('/covered' + '/elsewhere')
