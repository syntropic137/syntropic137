#!/usr/bin/env node
// Boundary facts for the syn-ui data-layer fitness functions (ADR-074).
//
// Parses every .ts/.js/.mjs/.svelte file under the given directories with the
// real parsers (the `typescript` compiler API; `svelte/compiler` for .svelte,
// whose <script> blocks and markup expressions are then parsed with
// TypeScript too) and writes ONE JSON file of facts the pytest checks in
// ci/fitness/code_quality/test_syn_ui_*.py consume. Nothing here decides
// what is allowed: it only reports what the code says.
//
// Per file: imports, re-exports, local exports, top-level declarations,
// call expressions (callee chain, folded first argument, literal `method`),
// dynamic imports, references to imported bindings and to `fetch`, and every
// folded string expression. A file that does not parse is reported with
// `parse_error`; the checks treat that as a violation, never a skip.
//
// Usage: node boundary-facts.mjs --root <repo> --out <facts.json> <dir> [<dir> ...]
import { createRequire } from 'node:module'
import { existsSync, readdirSync, readFileSync, statSync, writeFileSync } from 'node:fs'
import { dirname, join, relative, resolve } from 'node:path'
import { pathToFileURL } from 'node:url'

const argv = process.argv.slice(2)
let root = process.cwd()
let out = null
const dirs = []
for (let i = 0; i < argv.length; i++) {
  if (argv[i] === '--root') root = resolve(argv[++i])
  else if (argv[i] === '--out') out = resolve(argv[++i])
  else dirs.push(argv[i])
}
if (!out || dirs.length === 0) {
  console.error('usage: boundary-facts.mjs --root <repo> --out <facts.json> <dir> [<dir> ...]')
  process.exit(2)
}

// typescript and svelte are devDependencies of apps/syn-ui; resolve them from there.
const requireFromApp = createRequire(join(root, 'apps', 'syn-ui', 'package.json'))
const ts = requireFromApp('typescript')
const svelteCompiler = await import(pathToFileURL(requireFromApp.resolve('svelte/compiler')).href)
const parseSvelte = svelteCompiler.parse ?? svelteCompiler.default.parse

const SUFFIXES = ['.ts', '.js', '.mjs', '.svelte']
const SKIP = new Set(['node_modules', 'dist', '.dist', '.results', '.report', '.svelte-kit'])

function* walk(dir) {
  if (!existsSync(dir)) return
  for (const name of readdirSync(dir).sort()) {
    if (SKIP.has(name)) continue
    const p = join(dir, name)
    if (statSync(p).isDirectory()) yield* walk(p)
    else if (SUFFIXES.some((s) => name.endsWith(s))) yield p
  }
}

const rel = (p) => relative(root, p).split('\\').join('/')

// ---------------------------------------------------------------------------
// Module resolution: relative paths and workspace packages (package.json exports)
// ---------------------------------------------------------------------------

const packages = new Map()
for (const parent of ['apps', 'packages', join('packages', 'syn-ui')]) {
  const base = join(root, parent)
  if (!existsSync(base)) continue
  for (const name of readdirSync(base)) {
    const manifest = join(base, name, 'package.json')
    if (!existsSync(manifest)) continue
    const pkg = JSON.parse(readFileSync(manifest, 'utf8'))
    if (pkg.name) packages.set(pkg.name, { dir: join(base, name), exports: pkg.exports ?? {} })
  }
}

const RESOLVE = ['', '.ts', '.js', '.mjs', '.svelte', '/index.ts', '/index.js']

function resolveFile(base) {
  const candidates = RESOLVE.map((s) => base + s)
  if (base.endsWith('.js')) candidates.push(base.slice(0, -3) + '.ts')
  return candidates.find((c) => existsSync(c) && statSync(c).isFile()) ?? null
}

function exportTarget(value) {
  if (typeof value === 'string') return value
  if (value && typeof value === 'object') return value.import ?? value.svelte ?? value.default ?? value.types ?? null
  return null
}

/** The repo-relative file `spec` names from `importer`, or null (external / unresolvable). */
function resolveSpec(importer, spec) {
  const bare = spec.split('?')[0]
  if (bare.startsWith('.')) {
    const hit = resolveFile(resolve(dirname(importer), bare))
    return hit ? rel(hit) : null
  }
  const m = /^(@[^/]+\/[^/]+|[^/@][^/]*)(\/.*)?$/.exec(bare)
  if (!m) return null
  const pkg = packages.get(m[1])
  if (!pkg) return null
  const sub = '.' + (m[2] ?? '')
  const exports = typeof pkg.exports === 'string' ? { '.': pkg.exports } : pkg.exports
  let target = exportTarget(exports[sub])
  if (!target) {
    for (const [key, value] of Object.entries(exports)) {
      if (!key.includes('*')) continue
      const [pre, post] = key.split('*')
      if (sub.startsWith(pre) && sub.endsWith(post) && sub.length >= pre.length + post.length) {
        const star = sub.slice(pre.length, sub.length - post.length)
        target = exportTarget(value)?.replace('*', star) ?? null
        break
      }
    }
  }
  // A workspace package whose exports do not name this subpath still resolves to that
  // package, so a boundary check sees which package it is (never "external").
  const hit = target ? resolveFile(join(pkg.dir, target)) : null
  return hit ? rel(hit) : rel(join(pkg.dir, 'package.json'))
}

// ---------------------------------------------------------------------------
// TypeScript walking
// ---------------------------------------------------------------------------

const SK = ts.SyntaxKind

/** Fold a string expression: {kind: 'literal'|'pattern', value} or null. Substitutions become \u0000. */
function fold(node) {
  if (!node) return null
  if (ts.isParenthesizedExpression(node) || ts.isAsExpression(node) || ts.isSatisfiesExpression?.(node) || ts.isTypeAssertionExpression(node)) {
    return fold(node.expression)
  }
  if (ts.isStringLiteral(node) || ts.isNoSubstitutionTemplateLiteral(node)) return { kind: 'literal', value: node.text }
  if (ts.isTemplateExpression(node)) {
    let value = node.head.text
    for (const span of node.templateSpans) value += '\u0000' + span.literal.text
    return { kind: 'pattern', value }
  }
  if (ts.isBinaryExpression(node) && node.operatorToken.kind === SK.PlusToken) {
    const left = fold(node.left)
    const right = fold(node.right)
    if (!left || !right) return null
    return { kind: left.kind === 'literal' && right.kind === 'literal' ? 'literal' : 'pattern', value: left.value + right.value }
  }
  return null
}

/** Runs of foldable operands in a `+` chain (for `'/ap' + 'i/' + x`). */
function plusOperands(node, outList) {
  if (ts.isBinaryExpression(node) && node.operatorToken.kind === SK.PlusToken) {
    plusOperands(node.left, outList)
    plusOperands(node.right, outList)
  } else outList.push(node)
}

function calleeChain(node) {
  while (ts.isParenthesizedExpression(node) || ts.isNonNullExpression(node) || ts.isAsExpression(node)) node = node.expression
  if (ts.isBinaryExpression(node) && node.operatorToken.kind === SK.CommaToken) return calleeChain(node.right)
  if (ts.isIdentifier(node)) return [node.text]
  if (node.kind === SK.ThisKeyword) return ['this']
  if (ts.isPropertyAccessExpression(node)) {
    const head = calleeChain(node.expression)
    return head ? [...head, node.name.text] : null
  }
  if (ts.isElementAccessExpression(node)) {
    const head = calleeChain(node.expression)
    const key = fold(node.argumentExpression)
    return head && key?.kind === 'literal' ? [...head, key.value] : null
  }
  if (ts.isCallExpression(node)) {
    const head = calleeChain(node.expression)
    return head ? [...head, '()'] : null
  }
  return null
}

function bindingNames(name, outList) {
  if (ts.isIdentifier(name)) outList.push(name.text)
  else for (const el of name.elements) if (!ts.isOmittedExpression(el)) bindingNames(el.name, outList)
  return outList
}

function hasModifier(node, kind) {
  return (ts.canHaveModifiers(node) ? ts.getModifiers(node) : undefined)?.some((m) => m.kind === kind) ?? false
}

function inType(node) {
  for (let p = node.parent; p; p = p.parent) {
    if (ts.isTypeNode(p) && !ts.isExpressionWithTypeArguments(p)) return true
    if (ts.isInterfaceDeclaration(p) || ts.isTypeAliasDeclaration(p)) return true
  }
  return false
}

/** Is this identifier a reference (not a declaration name, property name or specifier)? */
function isReference(id) {
  const p = id.parent
  if (!p) return false
  if ((ts.isPropertyAccessExpression(p) || ts.isPropertyAccessChain?.(p)) && p.name === id) return false
  if ((ts.isPropertyAssignment(p) || ts.isPropertyDeclaration(p) || ts.isMethodDeclaration(p) || ts.isPropertySignature(p) || ts.isMethodSignature(p) || ts.isGetAccessor(p) || ts.isSetAccessor(p) || ts.isEnumMember(p)) && p.name === id) return false
  if ((ts.isVariableDeclaration(p) || ts.isParameter(p) || ts.isFunctionDeclaration(p) || ts.isFunctionExpression(p) || ts.isClassDeclaration(p) || ts.isClassExpression(p) || ts.isInterfaceDeclaration(p) || ts.isTypeAliasDeclaration(p) || ts.isEnumDeclaration(p) || ts.isTypeParameterDeclaration(p)) && p.name === id) return false
  if (ts.isBindingElement(p)) return false
  if (ts.isImportSpecifier(p) || ts.isExportSpecifier(p) || ts.isImportClause(p) || ts.isNamespaceImport(p) || ts.isNamespaceExport(p) || ts.isImportEqualsDeclaration(p)) return false
  if (ts.isLabeledStatement(p) || ts.isBreakOrContinueStatement(p)) return false
  if (ts.isJsxAttribute?.(p)) return false
  return !inType(id)
}

/** `'x'` in `import .. from 'x'`, `export .. from 'x'`, `import('x')`, `require('x')`. */
function isModuleSpecifier(node) {
  const p = node.parent
  if (!p) return false
  if (ts.isImportDeclaration(p) || ts.isExportDeclaration(p) || ts.isExternalModuleReference(p)) return true
  if (ts.isCallExpression(p) && p.arguments[0] === node) {
    return p.expression.kind === SK.ImportKeyword || (ts.isIdentifier(p.expression) && p.expression.text === 'require')
  }
  return false
}

function createFacts(path) {
  return {
    path,
    kind: path.endsWith('.svelte') ? 'svelte' : 'ts',
    parse_error: null,
    imports: [],
    dynamic_imports: [],
    reexports: [],
    exports: [],
    decls: [],
    calls: [],
    refs: [],
    member_fetch: [],
    strings: [],
  }
}

/**
 * Walk one parsed unit (a whole .ts file, one <script>, or one markup expression).
 * `offset` maps the unit's positions to the file; `lineOf` turns a file offset into a line.
 */
function walkUnit(sf, facts, absPath, offset, lineOf, { topLevel }) {
  const line = (node) => lineOf(offset + node.getStart(sf))
  const declOf = new Map()

  if (topLevel) {
    for (const st of sf.statements) {
      const exported = hasModifier(st, SK.ExportKeyword)
      const isDefault = hasModifier(st, SK.DefaultKeyword)
      if (ts.isImportDeclaration(st)) {
        const spec = st.moduleSpecifier.text
        const resolved = resolveSpec(absPath, spec)
        const clause = st.importClause
        const typeOnly = clause?.isTypeOnly ?? false
        const base = { spec, resolved, line: line(st) }
        if (!clause) facts.imports.push({ ...base, local: null, imported: null, type_only: false })
        else {
          if (clause.name) facts.imports.push({ ...base, local: clause.name.text, imported: 'default', type_only: typeOnly })
          const nb = clause.namedBindings
          if (nb && ts.isNamespaceImport(nb)) facts.imports.push({ ...base, local: nb.name.text, imported: '*', type_only: typeOnly })
          if (nb && ts.isNamedImports(nb)) {
            for (const el of nb.elements) {
              facts.imports.push({ ...base, local: el.name.text, imported: (el.propertyName ?? el.name).text, type_only: typeOnly || el.isTypeOnly })
            }
          }
        }
        continue
      }
      if (ts.isImportEqualsDeclaration(st) && ts.isExternalModuleReference(st.moduleReference)) {
        const spec = fold(st.moduleReference.expression)?.value ?? null
        facts.imports.push({ spec, resolved: spec ? resolveSpec(absPath, spec) : null, line: line(st), local: st.name.text, imported: '*', type_only: st.isTypeOnly })
        continue
      }
      if (ts.isExportDeclaration(st)) {
        const typeOnly = st.isTypeOnly
        if (st.moduleSpecifier) {
          const spec = st.moduleSpecifier.text
          const base = { spec, resolved: resolveSpec(absPath, spec), line: line(st) }
          if (!st.exportClause) facts.reexports.push({ ...base, local: '*', exported: null, type_only: typeOnly })
          else if (ts.isNamespaceExport(st.exportClause)) facts.reexports.push({ ...base, local: '*', exported: st.exportClause.name.text, type_only: typeOnly })
          else for (const el of st.exportClause.elements) facts.reexports.push({ ...base, local: (el.propertyName ?? el.name).text, exported: el.name.text, type_only: typeOnly || el.isTypeOnly })
        } else if (st.exportClause && ts.isNamedExports(st.exportClause)) {
          for (const el of st.exportClause.elements) facts.exports.push({ local: (el.propertyName ?? el.name).text, exported: el.name.text, kind: 'list', type_only: typeOnly || el.isTypeOnly, line: line(el) })
        }
        continue
      }
      if (ts.isExportAssignment(st)) {
        const local = ts.isIdentifier(st.expression) ? st.expression.text : null
        facts.exports.push({ local, exported: 'default', kind: 'default', type_only: false, line: line(st) })
        if (!local) declOf.set(st, ['default'])
        continue
      }
      let names = []
      let kind = null
      let alias = null
      if (ts.isFunctionDeclaration(st)) {
        names = [st.name?.text ?? 'default']
        kind = 'function'
      } else if (ts.isClassDeclaration(st)) {
        names = [st.name?.text ?? 'default']
        kind = 'class'
      } else if (ts.isVariableStatement(st)) {
        for (const d of st.declarationList.declarations) bindingNames(d.name, names)
        const init = st.declarationList.declarations[0]?.initializer
        kind = init && (ts.isArrowFunction(init) || ts.isFunctionExpression(init)) ? 'arrow' : 'const'
        // `const x = y` / `const x = ns.y`: x is another name for y.
        const only = st.declarationList.declarations.length === 1 ? st.declarationList.declarations[0] : null
        if (only && ts.isIdentifier(only.name) && only.initializer) alias = calleeChain(only.initializer)
      } else if (ts.isEnumDeclaration(st)) {
        names = [st.name.text]
        kind = 'enum'
      } else if (ts.isInterfaceDeclaration(st) || ts.isTypeAliasDeclaration(st)) {
        names = [st.name.text]
        kind = 'type'
      } else if (ts.isModuleDeclaration(st)) {
        kind = 'namespace'
        names = ts.isIdentifier(st.name) ? [st.name.text] : []
      }
      if (names.length) {
        declOf.set(st, names)
        facts.decls.push({ names, kind, line: line(st), refs: [], alias })
        if (exported) {
          for (const n of names) facts.exports.push({ local: n, exported: isDefault ? 'default' : n, kind, type_only: kind === 'type', line: line(st) })
        }
      }
    }
  }

  const importLocals = new Set(facts.imports.map((i) => i.local).filter(Boolean))
  const declByName = new Map()
  for (const d of facts.decls) for (const n of d.names) declByName.set(n, d)

  const visit = (node, decl) => {
    if (topLevel && node.parent === sf && declOf.has(node)) decl = declOf.get(node)[0]
    const declRec = decl ? declByName.get(decl) : undefined

    if (ts.isCallExpression(node)) {
      if (node.expression.kind === SK.ImportKeyword || (ts.isIdentifier(node.expression) && node.expression.text === 'require')) {
        const arg = fold(node.arguments[0])
        const spec = arg?.kind === 'literal' ? arg.value : null
        facts.dynamic_imports.push({ spec, resolved: spec ? resolveSpec(absPath, spec) : null, line: line(node), require: node.expression.kind !== SK.ImportKeyword })
      } else {
        const args = node.arguments.slice(0, 3).map((a) => fold(a) ?? { kind: 'dynamic', value: a.getText(sf).slice(0, 80) })
        const second = node.arguments[1]
        let method = null
        let methodKnown = true
        if (second) {
          if (ts.isObjectLiteralExpression(second)) {
            for (const prop of second.properties) {
              if (ts.isSpreadAssignment(prop)) methodKnown = false
              else if (prop.name && ts.isIdentifier(prop.name) && prop.name.text === 'method') {
                const v = ts.isPropertyAssignment(prop) ? fold(prop.initializer) : null
                if (v?.kind === 'literal') method = v.value
                else methodKnown = false
              }
            }
          } else methodKnown = false
        }
        facts.calls.push({
          callee: calleeChain(node.expression),
          line: line(node),
          decl: decl ?? null,
          args,
          method,
          method_known: methodKnown,
        })
      }
    }

    if (ts.isIdentifier(node) && isReference(node)) {
      if (node.text === 'fetch' || importLocals.has(node.text)) facts.refs.push({ name: node.text, line: line(node) })
      if (declRec && (declByName.has(node.text) || importLocals.has(node.text)) && node.text !== decl) declRec.refs.push(node.text)
    }
    if (ts.isShorthandPropertyAssignment(node)) {
      if (node.name.text === 'fetch' || importLocals.has(node.name.text)) facts.refs.push({ name: node.name.text, line: line(node) })
      if (declRec && (declByName.has(node.name.text) || importLocals.has(node.name.text))) declRec.refs.push(node.name.text)
    }
    if (ts.isPropertyAccessExpression(node) && node.name.text === 'fetch') facts.member_fetch.push(line(node))
    if (ts.isElementAccessExpression(node) && fold(node.argumentExpression)?.value === 'fetch') facts.member_fetch.push(line(node))
    if (ts.isBindingElement(node) && ((node.propertyName && fold(node.propertyName)?.value === 'fetch') || (node.propertyName && ts.isIdentifier(node.propertyName) && node.propertyName.text === 'fetch') || (!node.propertyName && ts.isIdentifier(node.name) && node.name.text === 'fetch'))) {
      facts.member_fetch.push(line(node))
    }

    if (ts.isBinaryExpression(node) && node.operatorToken.kind === SK.PlusToken && !(ts.isBinaryExpression(node.parent) && node.parent.operatorToken.kind === SK.PlusToken)) {
      const ops = []
      plusOperands(node, ops)
      let run = null
      for (const op of [...ops, null]) {
        const f = op ? fold(op) : null
        if (f) run = run ? { value: run.value + f.value, line: run.line } : { value: f.value, line: line(op) }
        else if (run) {
          facts.strings.push(run)
          run = null
        }
      }
    }
    if (ts.isImportTypeNode(node) && ts.isLiteralTypeNode(node.argument) && ts.isStringLiteral(node.argument.literal)) {
      const spec = node.argument.literal.text
      facts.imports.push({ spec, resolved: resolveSpec(absPath, spec), line: line(node), local: null, imported: '*', type_only: true })
    }
    if ((ts.isStringLiteral(node) || ts.isNoSubstitutionTemplateLiteral(node) || ts.isTemplateExpression(node)) && !isModuleSpecifier(node) && !inType(node)) {
      const f = fold(node)
      if (f) facts.strings.push({ value: f.value, line: line(node) })
    }
    ts.forEachChild(node, (child) => visit(child, decl))
  }
  visit(sf, null)
}

function parseErrors(sf) {
  const diags = sf.parseDiagnostics ?? []
  return diags.map((d) => ts.flattenDiagnosticMessageText(d.messageText, '\n'))
}

function lineIndex(text) {
  const starts = [0]
  for (let i = 0; i < text.length; i++) if (text[i] === '\n') starts.push(i + 1)
  return (offset) => {
    let lo = 0
    let hi = starts.length - 1
    while (lo < hi) {
      const mid = (lo + hi + 1) >> 1
      if (starts[mid] <= offset) lo = mid
      else hi = mid - 1
    }
    return lo + 1
  }
}

function scriptKind(path) {
  if (path.endsWith('.js') || path.endsWith('.mjs')) return ts.ScriptKind.JS
  return ts.ScriptKind.TS
}

function factsForTs(absPath, text) {
  const facts = createFacts(rel(absPath))
  const sf = ts.createSourceFile(absPath, text, ts.ScriptTarget.Latest, true, scriptKind(absPath))
  const errors = parseErrors(sf)
  if (errors.length) {
    facts.parse_error = errors[0]
    return facts
  }
  walkUnit(sf, facts, absPath, 0, lineIndex(text), { topLevel: true })
  return facts
}

// Svelte AST node types that are Svelte's own (everything else with a `type` is ESTree).
const PATTERNS = new Set(['ObjectPattern', 'ArrayPattern', 'AssignmentPattern', 'RestElement'])

/** Every ESTree node directly under Svelte markup, with whether it sits in a binding position. */
function markupExpressions(fragment, found) {
  const visit = (node, key) => {
    if (!node || typeof node !== 'object') return
    if (Array.isArray(node)) {
      for (const n of node) visit(n, key)
      return
    }
    const type = node.type
    if (typeof type === 'string' && typeof node.start === 'number' && isEstree(type)) {
      // Snippet parameters and each-block contexts are bindings (`p: T`, `{ a, b }`), not expressions.
      found.push({ node, binding: key === 'parameters' || key === 'context' || PATTERNS.has(type) })
      return
    }
    for (const [k, value] of Object.entries(node)) {
      if (k === 'parent' || k === 'metadata') continue
      if (value && typeof value === 'object') visit(value, k)
    }
  }
  visit(fragment, null)
}

const SVELTE_TYPES = /^(Root|Fragment|Text|Comment|ExpressionTag|HtmlTag|ConstTag|DebugTag|RenderTag|AttachTag|IfBlock|EachBlock|AwaitBlock|KeyBlock|SnippetBlock|RegularElement|Component|SvelteComponent|SvelteElement|SvelteSelf|SvelteFragment|SvelteHead|SvelteBody|SvelteWindow|SvelteDocument|SvelteBoundary|SvelteOptionsRaw|SvelteOptions|SlotElement|TitleElement|Attribute|SpreadAttribute|AnimateDirective|BindDirective|ClassDirective|LetDirective|OnDirective|StyleDirective|TransitionDirective|UseDirective|Script|StyleSheet|Rule|Atrule|Block|Declaration|SelectorList|ComplexSelector|RelativeSelector|TypeSelector|ClassSelector|IdSelector|AttributeSelector|PseudoClassSelector|PseudoElementSelector|Combinator|Nth|Percentage|NestingSelector)$/

function isEstree(type) {
  return !SVELTE_TYPES.test(type)
}

function factsForSvelte(absPath, text) {
  const facts = createFacts(rel(absPath))
  let ast
  try {
    ast = parseSvelte(text, { modern: true })
  } catch (error) {
    facts.parse_error = String(error?.message ?? error)
    return facts
  }
  const lineOf = lineIndex(text)
  for (const script of [ast.module, ast.instance]) {
    if (!script) continue
    const start = script.content.start
    const end = script.content.end
    const body = text.slice(start, end)
    const sf = ts.createSourceFile(absPath + '.ts', body, ts.ScriptTarget.Latest, true, ts.ScriptKind.TS)
    const errors = parseErrors(sf)
    if (errors.length) {
      facts.parse_error = `<script>: ${errors[0]}`
      return facts
    }
    walkUnit(sf, facts, absPath, start, lineOf, { topLevel: true })
  }
  const exprs = []
  markupExpressions(ast.fragment, exprs)
  for (const { node, binding } of exprs) {
    const src = text.slice(node.start, node.end)
    let wrapped
    let lead
    if (node.type === 'VariableDeclaration') {
      wrapped = src
      lead = 0
    } else if (binding) {
      wrapped = `(function(${src}){})`
      lead = 10
    } else {
      wrapped = `(${src})`
      lead = 1
    }
    const sf = ts.createSourceFile(absPath + '.expr.ts', wrapped, ts.ScriptTarget.Latest, true, ts.ScriptKind.TS)
    const errors = parseErrors(sf)
    if (errors.length) {
      facts.parse_error = `markup expression at line ${lineOf(node.start)}: ${errors[0]}`
      return facts
    }
    walkUnit(sf, facts, absPath, node.start - lead, lineOf, { topLevel: false })
  }
  // Static attribute text in markup (href="/api/x") is a string a component wrote.
  const attrs = []
  const visitAttrs = (node) => {
    if (!node || typeof node !== 'object') return
    if (Array.isArray(node)) return node.forEach(visitAttrs)
    if (node.type === 'Attribute' && Array.isArray(node.value)) {
      for (const v of node.value) if (v.type === 'Text') attrs.push({ value: v.data, line: lineOf(v.start) })
    }
    for (const [key, value] of Object.entries(node)) if (key !== 'parent' && key !== 'metadata' && value && typeof value === 'object') visitAttrs(value)
  }
  visitAttrs(ast.fragment)
  facts.strings.push(...attrs)
  return facts
}

const files = []
for (const dir of dirs) for (const file of walk(resolve(root, dir))) files.push(file)
const result = { root: '.', files: [] }
for (const file of [...new Set(files)].sort()) {
  const text = readFileSync(file, 'utf8')
  result.files.push(file.endsWith('.svelte') ? factsForSvelte(file, text) : factsForTs(file, text))
}
writeFileSync(out, JSON.stringify(result))
const broken = result.files.filter((f) => f.parse_error)
console.error(`boundary-facts: ${result.files.length} files, ${broken.length} parse errors`)
