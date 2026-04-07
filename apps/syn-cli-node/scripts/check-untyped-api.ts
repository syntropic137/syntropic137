/**
 * CI gate: ban untyped API client usage in CLI commands.
 *
 * All commands must use the typed client (../client/typed.js) which provides
 * compile-time path validation and fully typed responses from the OpenAPI spec.
 * Fails if any command file imports the deprecated untyped client.
 *
 * Usage: npx tsx scripts/check-untyped-api.ts
 */

import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const commandsDir = path.resolve(__dirname, "../src/commands");

function findTsFiles(dir: string): string[] {
  const results: string[] = [];
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const fullPath = path.join(dir, entry.name);
    if (entry.isDirectory()) {
      results.push(...findTsFiles(fullPath));
    } else if (entry.name.endsWith(".ts")) {
      results.push(fullPath);
    }
  }
  return results;
}

const UNTYPED_IMPORT = /from\s+["']\.\.?\/(?:\.\.\/)?client\/api(\.js)?["']/;

const files = findTsFiles(commandsDir);
const offenders: string[] = [];

for (const file of files) {
  const content = fs.readFileSync(file, "utf-8");
  if (UNTYPED_IMPORT.test(content)) {
    offenders.push(path.relative(path.resolve(__dirname, ".."), file));
  }
}

if (offenders.length > 0) {
  console.error(`Found ${offenders.length} file(s) using the deprecated untyped API client:`);
  for (const f of offenders) {
    console.error(`  ${f}`);
  }
  console.error("");
  console.error("Use the typed client instead: import { api, unwrap } from \"../client/typed.js\"");
  process.exit(1);
}

console.log("All commands use the typed client.");
process.exit(0);
