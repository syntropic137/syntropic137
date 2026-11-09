// Shared by the two test files beside it. Each claims the config dir the CLI
// resolves (through synPath, as every registry does) and expects to find
// nothing else there. If test files share a config dir, whichever file runs
// second sees the other's claim: the #2223 race, made deterministic.
import fs from "node:fs";
import { synPath } from "../../src/persistence/store.js";

/** Writes `<owner>.claim` into the config dir and returns what the dir holds. */
export function claimConfigDir(owner: string): string[] {
  fs.mkdirSync(synPath(), { recursive: true });
  fs.writeFileSync(synPath(`${owner}.claim`), owner);
  return fs.readdirSync(synPath()).sort();
}
