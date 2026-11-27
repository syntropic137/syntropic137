// Writes fixtures/screenshot.json, the file `screenshot.mjs --fixtures` reads,
// from the fixture world in src/fixtures/screenshotFixtures.ts (#1647).
// The JSON is committed; screenshotFixtures.test.ts fails when it is stale.

import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { screenshotFixturesJson } from "../src/fixtures/screenshotFixtures.ts";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const outputPath = path.resolve(__dirname, "../fixtures/screenshot.json");

fs.mkdirSync(path.dirname(outputPath), { recursive: true });
fs.writeFileSync(outputPath, screenshotFixturesJson(), "utf-8");
console.log(`Wrote ${outputPath}`);
