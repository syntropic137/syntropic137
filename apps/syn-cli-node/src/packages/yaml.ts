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

import { type Alias, type Document, LineCounter, type Node, parseDocument, visit } from "yaml";

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
  const problemAt = findUnsupported(doc);
  if (problemAt !== undefined) {
    const { line } = lineCounter.linePos(problemAt.offset);
    throw new YamlParseError(`${source}:${line}: ${problemAt.message}`);
  }
  return doc.toJS() as YamlValue;
}

/**
 * The first node the JSON upload cannot carry faithfully: an alias with no
 * anchor, an alias inside the node it names (a cycle `toJS` would recurse into
 * forever), or a 1.1 timestamp/binary that `JSON.stringify` would silently
 * rewrite. Checked on the AST so the error can name the line.
 */
function findUnsupported(doc: Document): { offset: number; message: string } | undefined {
  let found: { offset: number; message: string } | undefined;
  visit(doc, {
    Alias(_, node) {
      const target = node.resolve(doc);
      const offset = node.range?.[0] ?? 0;
      if (target === undefined) {
        found = { offset, message: "alias refers to an anchor not defined above it" };
        return visit.BREAK;
      }
      if (contains(target, node)) {
        found = { offset, message: `alias *${node.source} is inside the node it refers to (a cycle)` };
        return visit.BREAK;
      }
      return undefined;
    },
    Scalar(_, node) {
      const value: unknown = node.value;
      if (value === null || typeof value !== "object") return undefined;
      const kind = (value as object).constructor?.name ?? typeof value;
      found = {
        offset: node.range?.[0] ?? 0,
        message: `a YAML ${kind} has no JSON form; quote it to make it a string`,
      };
      return visit.BREAK;
    },
  });
  return found;
}

function contains(root: Node, needle: Alias): boolean {
  if (root === needle) return true;
  let hit = false;
  visit(root, {
    Alias(_, node) {
      if (node !== needle) return undefined;
      hit = true;
      return visit.BREAK;
    },
  });
  return hit;
}
