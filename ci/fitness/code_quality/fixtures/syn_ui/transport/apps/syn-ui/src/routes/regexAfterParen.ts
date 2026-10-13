// PROBE: a regex literal after a control-flow ) hides fetch from a hand tokenizer (review 2)
declare const ok: boolean
declare const x: string
export function go() {
  if (ok) /"/.test(x); fetch('/x'); const end = ""
  return end
}
