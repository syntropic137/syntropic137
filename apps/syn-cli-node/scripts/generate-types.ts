import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import openapiTS, { astToString } from "openapi-typescript";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const inputPath = path.resolve(__dirname, "../../../apps/syn-docs/openapi.json");
const outputDir = path.resolve(__dirname, "../src/generated");
const outputPath = path.join(outputDir, "api-types.ts");

async function main(): Promise<void> {
  if (!fs.existsSync(inputPath)) {
    console.error(`OpenAPI spec not found at ${inputPath}`);
    process.exit(1);
  }

  fs.mkdirSync(outputDir, { recursive: true });

  const source = new URL(`file://${inputPath}`);
  const ast = await openapiTS(source);
  const output = astToString(ast);

  const content = `// @generated — do not edit. Regenerate with: pnpm generate:types\n\n${output}`;
  fs.writeFileSync(outputPath, content, "utf-8");
  console.log(`Generated ${outputPath}`);
}

main();
