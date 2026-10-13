// HELPER: a stand-in transport for the planted resources tree
export interface RequestOptions {
  method?: string
  body?: unknown
  query?: unknown
  signal?: AbortSignal
}
export function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  return Promise.resolve({ path, options } as T)
}
export function fetchJSON<T>(url: string): Promise<T> {
  return Promise.resolve(url as T)
}
export function seg(value: string): string {
  return encodeURIComponent(value)
}
