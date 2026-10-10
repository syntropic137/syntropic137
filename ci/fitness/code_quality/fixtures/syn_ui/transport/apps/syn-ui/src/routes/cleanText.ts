// CLEAN: comments and lookalike words are not code
// never fetch( here, and no /api/v1 either
/* fetch(x) */
declare function prefetch(r: string): void
declare function refetch(): void
export function go() {
  prefetch('route')
  refetch()
  const u = 'https://example.com/a'
  const re = /"/g
  return [u, re]
}
