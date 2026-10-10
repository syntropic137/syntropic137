// PROBE: request renamed on import
import { request as send } from '../client'
export const x = () => send('/uncovered-alias')
