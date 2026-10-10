// PROBE: a /}/ regex inside a template interpolation hides fetch (review 2)
export const t = `${ /}/.source }`; fetch('/x')
