#!/usr/bin/env node
// Regenerate src/generated/api-types.ts from the API's OpenAPI spec, the same
// source apps/syn-cli-node and apps/syn-dashboard-ui generate from (#1182).
//
// Generated INTO this package rather than imported from a shared one: the
// plugin is published, and its emitted .d.ts files must not name a workspace
// package that npm consumers cannot install.
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import openapiTS, { astToString } from "openapi-typescript";

const here = path.dirname(fileURLToPath(import.meta.url));
const input = path.resolve(here, "../../../apps/syn-docs/openapi.json");
const outputDir = path.resolve(here, "../src/generated");
const output = path.join(outputDir, "api-types.ts");

if (!fs.existsSync(input)) {
  console.error(`OpenAPI spec not found at ${input}`);
  process.exit(1);
}
fs.mkdirSync(outputDir, { recursive: true });
const ast = await openapiTS(new URL(`file://${input}`));
const header = "// @generated -- do not edit. Regenerate with: just codegen\n\n";
fs.writeFileSync(output, header + astToString(ast), "utf-8");
console.log(`Generated ${output}`);
