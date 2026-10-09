// HELPER: planted cache wrapper
export function cached<T>(_name: string, _params: unknown[], load: (s?: AbortSignal) => Promise<T>, _o: unknown): Promise<T> {
  return load()
}
