/**
 * YAML loading for workflow packages, plugin manifests and frontmatter.
 *
 * Parses as YAML 1.1, the dialect of PyYAML's `safe_load`, which is what the
 * API and the domain use on every definition (`WorkflowDefinition.from_yaml`).
 * The CLI and the server must read the same file the same way: anchors,
 * aliases, merge keys (`<<: *x`) and 1.1 scalars (`yes`/`no`) included.
 *
 * WHY a real parser: the hand-rolled subset this replaced did not support
 * anchors or merge keys and did not notice them either. It collapsed the ten
 * phases of sdlc/implement-v3 into four with keys "0".."9" and reported a
 * successful install (#1618). Anything this parser cannot read is an error
 * naming the file and line, never a best guess.
 */

import { LineCounter, parseDocument, visit } from "yaml";

type YamlValue =
  | string
  | number
  | boolean
  | null
  | YamlValue[]
  | { [key: string]: YamlValue };

export class YamlParseError extends Error {
  override readonly name = "YamlParseError";
}

/**
 * Parse one YAML document. `source` names the input in error messages
 * (normally the file path).
 *
 * @throws YamlParseError on any syntax error, duplicate key, unresolved
 *   alias, multiple documents, or a value with no JSON form.
 */
export function parseYaml(input: string, source = "<yaml>"): YamlValue {
  const lineCounter = new LineCounter();
  const doc = parseDocument(input, {
    lineCounter,
    version: "1.1",
    merge: true,
    uniqueKeys: true,
    prettyErrors: true,
  });
  const problem = doc.errors[0];
  if (problem !== undefined) {
    const line = problem.linePos?.[0].line;
    const where = line === undefined ? source : `${source}:${line}`;
    throw new YamlParseError(`${where}: ${problem.message}`);
  }
  // A 1.1 timestamp or binary would come back as a Date or Uint8Array, which
  // the upload's JSON.stringify would silently rewrite. Refuse instead.
  let unresolved: number | undefined;
  visit(doc, {
    Alias(_, node) {
      if (node.resolve(doc) !== undefined) return undefined;
      unresolved = node.range?.[0] ?? 0;
      return visit.BREAK;
    },
  });
  if (unresolved !== undefined) {
    const { line } = lineCounter.linePos(unresolved);
    throw new YamlParseError(`${source}:${line}: alias refers to an anchor not defined above it`);
  }
  const value: unknown = doc.toJS();
  assertJsonShaped(value, source, "$");
  return value as YamlValue;
}

function assertJsonShaped(value: unknown, source: string, at: string): void {
  if (value === null || ["string", "number", "boolean"].includes(typeof value)) return;
  if (Array.isArray(value)) {
    value.forEach((item, i) => assertJsonShaped(item, source, `${at}[${i}]`));
    return;
  }
  if (Object.getPrototypeOf(value) === Object.prototype) {
    for (const [k, v] of Object.entries(value as Record<string, unknown>)) {
      assertJsonShaped(v, source, `${at}.${k}`);
    }
    return;
  }
  const kind = (value as object).constructor?.name ?? typeof value;
  throw new YamlParseError(
    `${source}: ${at} is a YAML ${kind}, which has no JSON form; quote it to make it a string`,
  );
}
