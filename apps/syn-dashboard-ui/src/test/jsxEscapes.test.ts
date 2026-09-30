/**
 * JSX does not process JavaScript escapes in attribute strings or text.
 *
 * `subtitle="View all \u2192"` renders the six characters backslash-u-2-1-9-2,
 * not an arrow: a JSX attribute string is HTML-like, and JSX text is text. Only
 * a JS expression (`{'\u2192'}`) or the literal character works. This shipped on
 * the workflow and trigger detail pages, so scan every .tsx for the pattern.
 *
 * Parsed with the TypeScript compiler rather than grepped, so an escape inside
 * a real JS string literal (which IS processed, and is fine) is never flagged.
 */

import { existsSync, readdirSync, readFileSync, statSync } from 'node:fs'
import { join, relative, resolve } from 'node:path'
import ts from 'typescript'
import { describe, expect, it } from 'vitest'

// Vitest runs from the package root; jsdom makes import.meta.url a non-file URL.
const SRC = resolve(process.cwd(), 'src')
const SKIP_DIRS = new Set(['generated', 'node_modules'])
const ESCAPE = /\\(u[0-9a-fA-F]{4}|u\{[0-9a-fA-F]+\}|x[0-9a-fA-F]{2})/

function tsxFiles(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name)
    if (statSync(path).isDirectory()) return SKIP_DIRS.has(name) ? [] : tsxFiles(path)
    return path.endsWith('.tsx') ? [path] : []
  })
}

/** Raw source of every JSX attribute string and JSX text node carrying an escape. */
function unprocessedJsxEscapes(fileName: string, source: string): string[] {
  const file = ts.createSourceFile(fileName, source, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX)
  const found: string[] = []
  const visit = (node: ts.Node): void => {
    const raw =
      ts.isJsxText(node) ? node.getText(file)
      : ts.isJsxAttribute(node) && node.initializer && ts.isStringLiteral(node.initializer)
        ? node.initializer.getText(file)
        : null
    if (raw !== null && ESCAPE.test(raw)) {
      const { line } = file.getLineAndCharacterOfPosition(node.getStart(file))
      found.push(`${fileName}:${line + 1}: ${raw.trim()}`)
    }
    ts.forEachChild(node, visit)
  }
  visit(file)
  return found
}

describe('JSX escape guard', () => {
  it('flags escapes in JSX attribute strings and JSX text, and nothing else', () => {
    const probe = [
      'const ok = <A b={\'\\u2192\'} c="plain" />',
      'const js = \'\\u2014\'',
      'const bad = <A subtitle="View all \\u2192" />',
      'const text = <p>Next \\x3e</p>',
    ].join('\n')
    const hits = unprocessedJsxEscapes('probe.tsx', probe)
    expect(hits).toHaveLength(2)
    expect(hits[0]).toContain('View all')
    expect(hits[1]).toContain('Next')
  })

  it('no .tsx under src renders a literal escape sequence', () => {
    // Guard the guard: scanning the wrong directory would pass vacuously.
    expect(existsSync(join(SRC, 'main.tsx'))).toBe(true)
    const offenders = tsxFiles(SRC).flatMap((path) =>
      unprocessedJsxEscapes(relative(SRC, path), readFileSync(path, 'utf-8')),
    )
    expect(offenders).toEqual([])
  })
})
