/**
 * Generate (or check) this package's TypeScript view of the syn-api contract.
 *
 * Two modes, one implementation:
 *
 *   tsx scripts/generate-types.ts            writes src/generated/api-types.ts
 *   tsx scripts/generate-types.ts --check    exits 1 if that file is stale
 *
 * They share a body deliberately. `apps/syn-cli-node` splits the same job over
 * two scripts that each re-declare the spec path and the @generated banner, so
 * editing one and not the other makes the drift check report drift forever
 * against output nobody can produce. There is nothing to keep in sync here.
 *
 * The spec itself is written by `uv run python scripts/extract_openapi.py`,
 * which `just codegen` runs first.
 */

import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import openapiTS, { astToString } from "openapi-typescript";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const specPath = path.resolve(__dirname, "../../../apps/syn-docs/openapi.json");
const outputPath = path.resolve(__dirname, "../src/generated/api-types.ts");

async function render(): Promise<string> {
  const ast = await openapiTS(new URL(`file://${specPath}`));
  return `// @generated — do not edit. Regenerate with: pnpm generate:types\n\n${astToString(ast)}`;
}

function firstDifferingLine(fresh: string, committed: string): number {
  const a = fresh.split("\n");
  const b = committed.split("\n");
  for (let i = 0; i < Math.max(a.length, b.length); i++) {
    if (a[i] !== b[i]) return i + 1;
  }
  return 0;
}

async function main(): Promise<void> {
  // A missing spec fails rather than skipping. The whole point of this script
  // is that staleness cannot pass unnoticed, and "input absent, exit 0" is the
  // loudest possible way to pass unnoticed.
  if (!fs.existsSync(specPath)) {
    console.error(`OpenAPI spec not found at ${specPath}`);
    console.error("Run: uv run python scripts/extract_openapi.py (or `just codegen`)");
    process.exit(1);
  }

  const fresh = await render();

  if (!process.argv.includes("--check")) {
    fs.mkdirSync(path.dirname(outputPath), { recursive: true });
    fs.writeFileSync(outputPath, fresh, "utf-8");
    console.log(`Generated ${outputPath}`);
    return;
  }

  if (!fs.existsSync(outputPath)) {
    console.error(`Generated types not found at ${outputPath}`);
    console.error("Run: pnpm generate:types");
    process.exit(1);
  }

  const committed = fs.readFileSync(outputPath, "utf-8");
  if (fresh === committed) {
    console.log("No drift detected — generated types are up to date.");
    return;
  }

  const line = firstDifferingLine(fresh, committed);
  console.error("API drift detected!");
  console.error(`  OpenAPI spec: ${specPath}`);
  console.error(`  Generated:    ${outputPath}`);
  console.error(`  First difference at line ${line}`);
  console.error("");
  console.error("Fix: run `pnpm generate:types` and commit the result.");
  process.exit(1);
}

main();
