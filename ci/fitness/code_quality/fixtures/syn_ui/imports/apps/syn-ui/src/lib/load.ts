// HELPER: binding module that only uses data internally
import { queryCache } from '@syn137/syn-ui-data'
export function resource(): unknown {
  return queryCache
}
