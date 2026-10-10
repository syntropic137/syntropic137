// PROBE: fetchJSON called with no import
declare const fetchJSON: (u: string) => Promise<unknown>
export const go = () => fetchJSON('/x')
