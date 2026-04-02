/**
 * CI script: detect drift between the OpenAPI spec and generated types.
 *
 * Regenerates api-types.ts into a temp file and diffs against the committed
 * version. Exits 1 if they differ — meaning someone changed the API spec
 * without running `pnpm generate:types`.
 *
 * Usage: npx tsx scripts/check-api-drift.ts
 */

import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import openapiTS, { astToString } from "openapi-typescript";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const specPath = path.resolve(__dirname, "../../../apps/syn-docs/openapi.json");
const committedPath = path.resolve(__dirname, "../src/generated/api-types.ts");

async function main(): Promise<void> {
  if (!fs.existsSync(specPath)) {
    console.error(`OpenAPI spec not found at ${specPath}`);
    console.error("Skipping drift check (spec file missing).");
    process.exit(0);
  }

  if (!fs.existsSync(committedPath)) {
    console.error(`Generated types not found at ${committedPath}`);
    console.error("Run: pnpm generate:types");
    process.exit(1);
  }

  console.log("Regenerating types from OpenAPI spec...");
  const source = new URL(`file://${specPath}`);
  const ast = await openapiTS(source);
  const freshOutput = `// @generated — do not edit. Regenerate with: pnpm generate:types\n\n${astToString(ast)}`;

  const committed = fs.readFileSync(committedPath, "utf-8");

  if (freshOutput === committed) {
    console.log("No drift detected — generated types are up to date.");
    process.exit(0);
  }

  // Find first differing line for helpful output
  const freshLines = freshOutput.split("\n");
  const committedLines = committed.split("\n");
  let firstDiff = -1;
  const maxLines = Math.max(freshLines.length, committedLines.length);
  for (let i = 0; i < maxLines; i++) {
    if (freshLines[i] !== committedLines[i]) {
      firstDiff = i + 1;
      break;
    }
  }

  console.error("API drift detected!");
  console.error(`  OpenAPI spec: ${specPath}`);
  console.error(`  Generated:    ${committedPath}`);
  if (firstDiff > 0) {
    console.error(`  First difference at line ${firstDiff}`);
    console.error(`    spec:      ${(freshLines[firstDiff - 1] ?? "").trim().slice(0, 80)}`);
    console.error(`    committed: ${(committedLines[firstDiff - 1] ?? "").trim().slice(0, 80)}`);
  }
  console.error("");
  console.error("Fix: run `pnpm generate:types` and commit the result.");
  process.exit(1);
}

main();
