// PROBE: request aliased through a const
import { request } from '../client'
const send = request
export const x = () => send('/uncovered-const-alias')
