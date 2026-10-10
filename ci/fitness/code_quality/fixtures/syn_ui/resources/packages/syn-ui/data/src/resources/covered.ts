// CLEAN: every request here has a composed fixture route
import { request, seg } from '../client'
import { cached } from '../keys'
export function getThing(id: string, signal?: AbortSignal) {
  return cached('getThing', [id], (s) => request(`/things/${seg(id)}`, { signal: s }), { signal })
}
export function makeThing(id: string) {
  return request(`/things/${seg(id)}/make`, { method: 'POST', body: { a: ')' } })
}
export function listThings(signal?: AbortSignal) {
  return load(signal)
}
async function load(signal?: AbortSignal) {
  const r = await request<{ things?: string[] }>('/things', { query: { q: 'x' }, signal })
  return r.things ?? []
}
export function thingStreamUrl(id: string): string {
  return `/sse/things/${seg(id)}`
}
function hidden(id: string) {
  return request(`/hidden/${seg(id)}`)
}
const arrow = async (signal?: AbortSignal) => request('/arrow', { signal })
export const exportedArrow = (id: string) => request(`/exported-arrow/${seg(id)}`)
export { hidden, arrow as renamedArrow }
export function joined() {
  return request('/covered' + '/uncovered')
}
export function joinedTemplate(id: string) {
  return request('/a/' + `${seg(id)}/b`, { method: 'PUT' })
}
    export function indented() {
      return request('/indented')
    }
export const renamedSpread = () => request('/renamed-spread')
export const viaHelperArray = () => request('/via-helper-array')
