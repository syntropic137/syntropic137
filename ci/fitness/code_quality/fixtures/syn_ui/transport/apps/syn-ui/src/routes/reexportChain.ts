// PROBE: transport through a two-level re-export chain
import { wire } from '../lib/chainB'
export const go = () => wire('/executions')
