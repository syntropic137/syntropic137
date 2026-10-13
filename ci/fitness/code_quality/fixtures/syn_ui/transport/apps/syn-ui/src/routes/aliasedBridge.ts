// PROBE: send is request, renamed in a binding bridge (review 2)
import { send } from '../lib/sendBridge'
export const go = () => send('/executions')
