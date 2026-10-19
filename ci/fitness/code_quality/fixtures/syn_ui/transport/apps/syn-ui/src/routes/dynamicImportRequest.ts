// PROBE: request through a dynamic import
export async function go() {
  const { request } = await import('@syn137/syn-ui-data')
  return request('/x')
}
