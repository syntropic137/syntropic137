import { readFileSync } from "node:fs";
import { defineConfig } from "tsup";

const pkg = JSON.parse(
  readFileSync(new URL("./package.json", import.meta.url), "utf-8"),
) as { version: string };

export default defineConfig({
  entry: { syn: "src/index.ts" },
  format: ["esm"],
  target: "node22",
  outDir: "dist",
  clean: true,
  splitting: false,
  sourcemap: false,
  dts: false,
  banner: { js: "#!/usr/bin/env node" },
  outExtension: () => ({ js: ".js" }),
  define: {
    __CLI_VERSION__: JSON.stringify(pkg.version),
  },
});
