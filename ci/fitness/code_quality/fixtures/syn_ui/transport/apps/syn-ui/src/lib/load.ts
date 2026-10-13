// CLEAN: the binding reads through the cache and exports its own function
import { queryCache } from '@syn137/syn-ui-data'
export function resource<T>(fetcher: () => Promise<T>): Promise<T> {
  void queryCache
  return fetcher()
}
