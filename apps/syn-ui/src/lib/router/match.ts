/**
 * Path matching for the app router. Plain functions so they unit-test in Node.
 *
 * Patterns are literal segments and `:name` params ("/executions/:executionId").
 * A trailing "/*" matches any rest (used for redirects).
 */
export type Params = Record<string, string>

export interface CompiledPattern {
  pattern: string
  regex: RegExp
  names: string[]
}

export function compilePattern(pattern: string): CompiledPattern {
  const names: string[] = []
  const wildcard = pattern.endsWith('/*')
  const body = (wildcard ? pattern.slice(0, -2) : pattern)
    .split('/')
    .filter(Boolean)
    .map((seg) => {
      if (seg.startsWith(':')) {
        names.push(seg.slice(1))
        return '/([^/]+)'
      }
      return '/' + seg.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
    })
    .join('')
  const source = `^${body}${wildcard ? '(?:/.*)?' : ''}/?$`
  return { pattern, regex: new RegExp(source === '^/?$' ? '^/?$' : source), names }
}

export function matchPattern(compiled: CompiledPattern, path: string): Params | null {
  const m = compiled.regex.exec(path)
  if (!m) return null
  const params: Params = {}
  compiled.names.forEach((name, i) => {
    try {
      params[name] = decodeURIComponent(m[i + 1] ?? '')
    } catch {
      params[name] = m[i + 1] ?? ''
    }
  })
  return params
}

/** Remove the deploy base ("/next/") from a pathname; always returns a path starting with "/". */
export function stripBase(pathname: string, base: string): string {
  const b = base.endsWith('/') ? base.slice(0, -1) : base
  if (b && (pathname === b || pathname.startsWith(b + '/'))) pathname = pathname.slice(b.length)
  return pathname.startsWith('/') ? pathname : '/' + pathname
}

/** Add the deploy base to an app path: ("/executions", "/next/") -> "/next/executions". */
export function withBase(path: string, base: string): string {
  const b = base.endsWith('/') ? base.slice(0, -1) : base
  return `${b}${path.startsWith('/') ? path : '/' + path}`
}
